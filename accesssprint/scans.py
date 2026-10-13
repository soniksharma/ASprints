"""Bounded local scan jobs backed by the Node Playwright worker."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from accesssprint.config import DEFAULT_MODEL
from accesssprint.store import Store, utc_now

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = APP_ROOT / "scanner" / "worker.mjs"


class ScanError(RuntimeError):
    pass


def run_worker(payload: dict, work_dir: Path, *, process_runner=subprocess.run) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    node = os.environ.get("ASPRINT_NODE_BINARY") or shutil.which("node") or "node"
    with tempfile.TemporaryDirectory(dir=work_dir, prefix="scan-") as temp_name:
        temp = Path(temp_name)
        input_path, output_path = temp / "input.json", temp / "output.json"
        input_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [node, str(WORKER_PATH), str(input_path), str(output_path)]
        try:
            result = process_runner(command, cwd=str(APP_ROOT), capture_output=True, text=True,
                                    timeout=300, shell=False, check=False)
        except subprocess.TimeoutExpired as error:
            raise ScanError("The browser scan timed out.") from error
        except OSError as error:
            raise ScanError("Node.js or the browser scanner could not be started.") from error
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "The browser scanner failed.").strip()[:800]
            raise ScanError(message)
        try:
            return json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ScanError("The browser scanner returned an invalid result.") from error


class ScanService:
    def __init__(self, store: Store, *, worker=None, work_dir: Path):
        self.store = store
        self.worker = worker or run_worker
        self.work_dir = Path(work_dir)
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="accesssprint-scan")
        self.futures = {}
        self._lock = threading.Lock()

    def start_scan(self, audit_id: str) -> dict:
        audit = self.store.get_audit(audit_id)
        if audit is None:
            raise ValueError("Audit not found.")
        if audit["archived"]:
            raise ValueError("Restore this audit before starting a scan.")
        scan_id = str(uuid.uuid4())
        started_at = utc_now()
        self.store.create_scan_run({"id": scan_id, "audit_id": audit_id, "status": "running",
                                    "started_at": started_at, "model_tag": DEFAULT_MODEL, "result": {"pages": []}})
        self.store.add_event(audit_id, "scan_started", {"scan_id": scan_id}, now=started_at)
        payload = {"runId": scan_id, "pages": [page["url"] for page in audit["pages"]]}
        future = self.executor.submit(self._execute, scan_id, audit, payload)
        with self._lock:
            self.futures[scan_id] = future
        return {"id": scan_id, "audit_id": audit_id, "status": "running", "started_at": started_at}

    def _execute(self, scan_id: str, audit: dict, payload: dict) -> None:
        try:
            output = self.worker(payload, self.work_dir)
            if not isinstance(output, dict) or output.get("status") not in {"completed", "partial", "failed"}:
                raise ScanError("The browser scanner returned an invalid scan status.")
            page_by_url = {page["url"]: page for page in audit["pages"]}
            for page in output.get("pages", []):
                if page.get("status") != "ok":
                    continue
                page_record = page_by_url.get(page.get("requested_url"))
                if page_record is None:
                    continue
                for violation in page.get("violations", [])[:300]:
                    if not isinstance(violation, dict) or not violation.get("rule_id"):
                        continue
                    self.store.create_finding({
                        "id": str(uuid.uuid4()), "scan_id": scan_id, "page_id": page_record["id"],
                        "rule_id": str(violation.get("rule_id", "unknown"))[:100],
                        "impact": violation.get("impact", "unknown"), "help": str(violation.get("help", ""))[:300],
                        "description": str(violation.get("description", ""))[:1200],
                        "help_url": str(violation.get("help_url", ""))[:500],
                        "nodes": violation.get("nodes", [])[:25], "review_status": "needs_review",
                    })
            status = output["status"]
            self.store.update_scan_run(scan_id, status=status, result=output,
                                       completed_at=utc_now(), axe_version=output.get("axe_version"))
            self.store.add_event(audit["id"], "scan_finished", {"scan_id": scan_id, "status": status})
        except Exception as error:
            output = {"run_id": scan_id, "status": "failed", "pages": [], "error": str(error)[:800]}
            self.store.update_scan_run(scan_id, status="failed", result=output, completed_at=utc_now())
            self.store.add_event(audit["id"], "scan_finished", {"scan_id": scan_id, "status": "failed"})

    def get_scan(self, scan_id: str) -> dict:
        run = self.store.get_scan_run(scan_id)
        if run is None:
            raise ValueError("Scan not found.")
        run["findings"] = self.store.list_findings(run["audit_id"], scan_id)
        return run

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)

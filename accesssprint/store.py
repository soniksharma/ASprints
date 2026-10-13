"""SQLite persistence for single-user, local AccessSprint audits."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    """Small SQLite repository with explicit transactions and foreign keys."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(self.path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self._initialize()

    def _initialize(self) -> None:
        with self._lock, self.connection:
            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS audits (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    client_name TEXT NOT NULL,
                    base_url TEXT NOT NULL,
                    auditor TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    label TEXT NOT NULL,
                    ordinal INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                    status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed')),
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    axe_version TEXT,
                    model_tag TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS findings (
                    id TEXT PRIMARY KEY,
                    scan_id TEXT NOT NULL REFERENCES scan_runs(id) ON DELETE CASCADE,
                    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    rule_id TEXT NOT NULL,
                    impact TEXT NOT NULL,
                    help TEXT NOT NULL,
                    description TEXT NOT NULL,
                    help_url TEXT NOT NULL DEFAULT '',
                    nodes_json TEXT NOT NULL DEFAULT '[]',
                    review_status TEXT NOT NULL DEFAULT 'needs_review'
                        CHECK(review_status IN ('needs_review','confirmed','fixed','not_applicable')),
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS manual_checks (
                    id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                    check_key TEXT NOT NULL,
                    label TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'not_checked'
                        CHECK(status IN ('not_checked','pass','issue')),
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    UNIQUE(audit_id, check_key)
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    audit_id TEXT NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_pages_audit ON pages(audit_id, ordinal);
                CREATE INDEX IF NOT EXISTS idx_scans_audit ON scan_runs(audit_id, started_at);
                CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id, impact);
                CREATE INDEX IF NOT EXISTS idx_events_audit ON audit_events(audit_id, created_at);
            """)

    def _dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def create_audit(self, audit: dict, pages: list[dict], manual_checks: list[dict] | None = None) -> None:
        now = audit.get("created_at") or utc_now()
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO audits(id,name,client_name,base_url,auditor,scope,archived,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,0,?,?)",
                (audit["id"], audit["name"], audit["client_name"], audit["base_url"],
                 audit["auditor"], audit["scope"], now, now),
            )
            self.connection.executemany(
                "INSERT INTO pages(id,audit_id,url,label,ordinal) VALUES(?,?,?,?,?)",
                [(page["id"], audit["id"], page["url"], page["label"], index)
                 for index, page in enumerate(pages)],
            )
            self.connection.executemany(
                "INSERT INTO manual_checks(id,audit_id,check_key,label,status,note,updated_at) "
                "VALUES(?,?,?,?,'not_checked','',?)",
                [(check["id"], audit["id"], check["key"], check["label"], now)
                 for check in manual_checks or []],
            )
            self.add_event(audit["id"], "audit_created", {"name": audit["name"]}, now=now)

    def get_audit(self, audit_id: str) -> dict | None:
        with self._lock:
            audit = self._dict(self.connection.execute("SELECT * FROM audits WHERE id=?", (audit_id,)).fetchone())
            if audit is None:
                return None
            audit["archived"] = bool(audit["archived"])
            audit["pages"] = [dict(row) for row in self.connection.execute(
                "SELECT * FROM pages WHERE audit_id=? AND active=1 ORDER BY ordinal", (audit_id,))]
            audit["manual_checks"] = [dict(row) for row in self.connection.execute(
                "SELECT * FROM manual_checks WHERE audit_id=? ORDER BY rowid", (audit_id,))]
            audit["scan_runs"] = [self._decode_run(row) for row in self.connection.execute(
                "SELECT * FROM scan_runs WHERE audit_id=? ORDER BY started_at DESC", (audit_id,))]
            audit["findings"] = self.list_findings(audit_id)
            audit["events"] = [self._dict(row) for row in self.connection.execute(
                "SELECT * FROM audit_events WHERE audit_id=? ORDER BY created_at DESC", (audit_id,))]
            return audit

    def list_audits(self, *, include_archived: bool = False) -> list[dict]:
        query = "SELECT * FROM audits" + ("" if include_archived else " WHERE archived=0") + " ORDER BY updated_at DESC"
        with self._lock:
            rows = self.connection.execute(query).fetchall()
            return [{**dict(row), "archived": bool(row["archived"])} for row in rows]

    def update_audit(self, audit_id: str, fields: dict, pages: list[dict] | None = None) -> bool:
        allowed = {"name", "client_name", "base_url", "auditor", "scope"}
        fields = {key: value for key, value in fields.items() if key in allowed}
        now = utc_now()
        with self._lock, self.connection:
            if not self.connection.execute("SELECT 1 FROM audits WHERE id=?", (audit_id,)).fetchone():
                return False
            if fields:
                assignments = ",".join(f"{key}=?" for key in fields)
                self.connection.execute(f"UPDATE audits SET {assignments},updated_at=? WHERE id=?",
                                        (*fields.values(), now, audit_id))
            if pages is not None:
                self.connection.execute("UPDATE pages SET active=0 WHERE audit_id=?", (audit_id,))
                self.connection.executemany(
                    "INSERT INTO pages(id,audit_id,url,label,ordinal) VALUES(?,?,?,?,?)",
                    [(page["id"], audit_id, page["url"], page["label"], index)
                     for index, page in enumerate(pages)],
                )
            self.add_event(audit_id, "audit_updated", fields, now=now)
            return True

    def archive_audit(self, audit_id: str, archived: bool) -> bool:
        with self._lock, self.connection:
            cursor = self.connection.execute("UPDATE audits SET archived=?,updated_at=? WHERE id=?",
                                             (int(archived), utc_now(), audit_id))
            if cursor.rowcount:
                self.add_event(audit_id, "audit_archived" if archived else "audit_restored", {})
            return cursor.rowcount > 0

    def delete_audit(self, audit_id: str) -> bool:
        with self._lock, self.connection:
            cursor = self.connection.execute("DELETE FROM audits WHERE id=?", (audit_id,))
            return cursor.rowcount > 0

    def create_scan_run(self, scan: dict) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO scan_runs(id,audit_id,status,started_at,completed_at,axe_version,model_tag,result_json) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (scan["id"], scan["audit_id"], scan.get("status", "running"), scan["started_at"],
                 scan.get("completed_at"), scan.get("axe_version"), scan.get("model_tag"),
                 json.dumps(scan.get("result", {}), ensure_ascii=False)),
            )

    def update_scan_run(self, scan_id: str, *, status: str, result: dict,
                        completed_at: str | None = None, axe_version: str | None = None) -> bool:
        with self._lock, self.connection:
            cursor = self.connection.execute(
                "UPDATE scan_runs SET status=?,result_json=?,completed_at=?,axe_version=COALESCE(?,axe_version) WHERE id=?",
                (status, json.dumps(result, ensure_ascii=False), completed_at or utc_now(), axe_version, scan_id),
            )
            return cursor.rowcount > 0

    def get_scan_run(self, scan_id: str) -> dict | None:
        with self._lock:
            row = self.connection.execute("SELECT * FROM scan_runs WHERE id=?", (scan_id,)).fetchone()
            return self._decode_run(row) if row else None

    def _decode_run(self, row: sqlite3.Row) -> dict:
        data = dict(row)
        data["result"] = json.loads(data.pop("result_json"))
        return data

    def create_finding(self, finding: dict) -> None:
        with self._lock, self.connection:
            self.connection.execute(
                "INSERT INTO findings(id,scan_id,page_id,rule_id,impact,help,description,help_url,nodes_json,review_status,note,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (finding["id"], finding["scan_id"], finding["page_id"], finding["rule_id"],
                 finding.get("impact", "unknown"), finding.get("help", ""), finding.get("description", ""),
                 finding.get("help_url", ""), json.dumps(finding.get("nodes", []), ensure_ascii=False),
                 finding.get("review_status", "needs_review"), finding.get("note", ""),
                 finding.get("created_at") or utc_now()),
            )

    def list_findings(self, audit_id: str, scan_id: str | None = None) -> list[dict]:
        sql = "SELECT f.*,p.url AS page_url,p.label AS page_label FROM findings f " \
              "JOIN scan_runs s ON s.id=f.scan_id JOIN pages p ON p.id=f.page_id WHERE s.audit_id=?"
        args: list[str] = [audit_id]
        if scan_id:
            sql += " AND s.id=?"
            args.append(scan_id)
        sql += " ORDER BY CASE f.impact WHEN 'critical' THEN 0 WHEN 'serious' THEN 1 WHEN 'moderate' THEN 2 ELSE 3 END, f.rule_id"
        with self._lock:
            output = []
            for row in self.connection.execute(sql, args):
                finding = dict(row)
                finding["nodes"] = json.loads(finding.pop("nodes_json"))
                output.append(finding)
            return output

    def get_finding(self, finding_id: str, audit_id: str) -> dict | None:
        matches = [finding for finding in self.list_findings(audit_id) if finding["id"] == finding_id]
        return matches[0] if matches else None

    def update_finding(self, finding_id: str, *, review_status: str, note: str) -> bool:
        with self._lock, self.connection:
            cursor = self.connection.execute("UPDATE findings SET review_status=?,note=? WHERE id=?",
                                             (review_status, note, finding_id))
            return cursor.rowcount > 0

    def update_manual_check(self, check_id: str, *, status: str, note: str) -> bool:
        with self._lock, self.connection:
            cursor = self.connection.execute("UPDATE manual_checks SET status=?,note=?,updated_at=? WHERE id=?",
                                             (status, note, utc_now(), check_id))
            return cursor.rowcount > 0

    def get_manual_check(self, check_id: str, audit_id: str) -> dict | None:
        with self._lock:
            return self._dict(self.connection.execute(
                "SELECT * FROM manual_checks WHERE id=? AND audit_id=?", (check_id, audit_id)).fetchone())

    def add_event(self, audit_id: str, event_type: str, payload: dict, *, now: str | None = None) -> None:
        import uuid
        self.connection.execute("INSERT INTO audit_events(id,audit_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)",
                                (str(uuid.uuid4()), audit_id, event_type,
                                 json.dumps(payload, ensure_ascii=False), now or utc_now()))

    def close(self) -> None:
        with self._lock:
            self.connection.close()

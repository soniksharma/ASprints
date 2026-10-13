"""Loopback HTTP API and static file server for AccessSprint."""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from accesssprint.audits import AuditError, AuditService
from accesssprint.config import DEFAULT_MODEL, DEFAULT_OLLAMA_URL, DEFAULT_PORT, DEFAULT_HOST, MAX_REQUEST_BYTES
from accesssprint.ollama import OllamaClient, OllamaError
from accesssprint.scans import ScanService
from accesssprint.store import Store

APP_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = APP_ROOT / "web"
AUDIT_ID = re.compile(r"^[0-9a-f-]{20,40}$", re.IGNORECASE)


def default_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "AccessSprint"


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AccessSprintHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def close_application(self):
        self.scans.close()
        self.store.close()


class Handler(BaseHTTPRequestHandler):
    server: AccessSprintHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        sys.stderr.write("[AccessSprint] " + (format % args) + "\n")

    def _headers(self, content_type: str, length: int, *, api: bool = False):
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                         "connect-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'")
        if api:
            self.send_header("Vary", "Accept")

    def send_json(self, status: int, payload=None):
        body = b"" if status == 204 else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._headers("application/json; charset=utf-8", len(body), api=True)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json_body(self) -> dict | None:
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self.send_json(400, {"error": "Content-Length must be a number."})
            return None
        if size < 0:
            self.send_json(400, {"error": "Invalid request body length."})
            return None
        if size > MAX_REQUEST_BYTES:
            self.send_json(413, {"error": "Request body is too large."})
            return None
        if size == 0:
            return {}
        if "application/json" not in self.headers.get("Content-Type", "").lower():
            self.send_json(415, {"error": "Send JSON with Content-Type: application/json."})
            return None
        try:
            value = json.loads(self.rfile.read(size))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(400, {"error": "Request body is not valid JSON."})
            return None
        if not isinstance(value, dict):
            self.send_json(400, {"error": "The JSON body must be an object."})
            return None
        return value

    def _ollama(self) -> OllamaClient:
        if self.server.ollama_client is not None:
            return self.server.ollama_client
        base_url = self.server.store.get_setting("ollama_base_url", DEFAULT_OLLAMA_URL)
        model = self.server.store.get_setting("ollama_model", DEFAULT_MODEL)
        return OllamaClient(base_url=base_url, model=model)

    def _api(self, method: str):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        pieces = path.strip("/").split("/")
        if pieces[:1] != ["api"]:
            return False
        query = parse_qs(parsed.query)
        try:
            if method == "GET" and path == "/api/health":
                return self.send_json(200, {"ok": True, "ollama": self._ollama().status(),
                                            "scanner": {"available": (APP_ROOT / "node_modules" / "playwright").exists()}})
            if method == "GET" and path == "/api/settings":
                return self.send_json(200, {"settings": {
                    "base_url": self.server.store.get_setting("ollama_base_url", DEFAULT_OLLAMA_URL),
                    "model": self.server.store.get_setting("ollama_model", DEFAULT_MODEL),
                }})
            if method == "GET" and path == "/api/audits":
                return self.send_json(200, {"audits": self.server.audits.list_audits()})
            if method == "POST" and path == "/api/audits":
                body = self._json_body()
                if body is None:
                    return True
                audit = self.server.audits.create_audit(body)
                return self.send_json(201, {"audit": audit})
            if len(pieces) == 3 and pieces[:2] == ["api", "audits"]:
                audit_id = pieces[2]
                if not AUDIT_ID.fullmatch(audit_id):
                    return self.send_json(404, {"error": "Audit not found."})
                if method == "GET":
                    return self.send_json(200, {"audit": self.server.audits.get_audit(audit_id)})
                if method == "PATCH":
                    body = self._json_body()
                    if body is None:
                        return True
                    return self.send_json(200, {"audit": self.server.audits.update_audit(audit_id, body)})
                if method == "DELETE":
                    self.server.audits.delete_audit(audit_id)
                    return self.send_json(204)
            if len(pieces) == 4 and pieces[:2] == ["api", "audits"]:
                audit_id, action = pieces[2], pieces[3]
                if not AUDIT_ID.fullmatch(audit_id):
                    return self.send_json(404, {"error": "Audit not found."})
                if method == "POST" and action == "scans":
                    if self._json_body() is None:
                        return True
                    scan = self.server.scans.start_scan(audit_id)
                    return self.send_json(202, {"scan": scan})
                if method == "POST" and action == "archive":
                    body = self._json_body()
                    if body is None:
                        return True
                    self.server.audits.archive_audit(audit_id, body.get("archived"))
                    return self.send_json(200, {"archived": body["archived"]})
                if method == "GET" and action == "scans":
                    return self.send_json(200, {"scans": self.server.audits.get_audit(audit_id)["scan_runs"]})
            if len(pieces) == 5 and pieces[:2] == ["api", "audits"] and pieces[3:] == ["scans", "compare"]:
                baseline = query.get("baseline", [""])[0]
                current = query.get("current", [""])[0]
                result = self.server.audits.compare_scans(pieces[2], baseline, current)
                return self.send_json(200, {"comparison": result})
            if len(pieces) == 3 and pieces[:2] == ["api", "scans"] and method == "GET":
                return self.send_json(200, {"scan": self.server.scans.get_scan(pieces[2])})
            if len(pieces) == 5 and pieces[:2] == ["api", "audits"]:
                audit_id, resource, resource_id = pieces[2], pieces[3], pieces[4]
                if not AUDIT_ID.fullmatch(audit_id):
                    return self.send_json(404, {"error": "Audit not found."})
                body = self._json_body() if method == "PATCH" else {}
                if body is None:
                    return True
                if method == "PATCH" and resource == "findings":
                    finding = self.server.audits.set_finding_review(audit_id, resource_id,
                                                                    body.get("status"), body.get("note", ""))
                    return self.send_json(200, {"finding": finding})
                if method == "PATCH" and resource == "manual-checks":
                    check = self.server.audits.set_manual_check(audit_id, resource_id,
                                                                body.get("status"), body.get("note", ""))
                    return self.send_json(200, {"manual_check": check})
            if method == "POST" and path in {"/api/ai/test", "/api/ai/explain", "/api/settings"}:
                body = self._json_body()
                if body is None:
                    return True
                if path == "/api/ai/test":
                    return self.send_json(200, {"test": self._ollama().test_connection()})
                if path == "/api/ai/explain":
                    audit_id, finding_id = body.get("audit_id", ""), body.get("finding_id", "")
                    finding = self.server.store.get_finding(finding_id, audit_id)
                    if finding is None:
                        return self.send_json(404, {"error": "Finding not found in this audit."})
                    return self.send_json(200, {"result": self._ollama().explain_finding(finding)})
                if path == "/api/settings":
                    base_url = body.get("base_url", DEFAULT_OLLAMA_URL)
                    model = body.get("model", DEFAULT_MODEL)
                    checked = OllamaClient(base_url=base_url, model=model)
                    self.server.store.set_setting("ollama_base_url", checked.base_url)
                    self.server.store.set_setting("ollama_model", checked.model)
                    return self.send_json(200, {"settings": {"base_url": checked.base_url, "model": checked.model}})
            return self.send_json(404, {"error": "API route not found."})
        except AuditError as error:
            status = 404 if "not found" in str(error).lower() else 400
            return self.send_json(status, {"error": str(error)})
        except (OllamaError, ValueError) as error:
            status = error.status_code if isinstance(error, OllamaError) else 400
            return self.send_json(status, {"error": str(error)})
        except Exception as error:
            self.log_message("API error: %s", type(error).__name__)
            return self.send_json(500, {"error": "AccessSprint could not complete that request."})

    def _static_file(self):
        requested = unquote(urlsplit(self.path).path)
        relative = "index.html" if requested in ("", "/") else requested.lstrip("/")
        root = WEB_ROOT.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return self.send_json(404, {"error": "Page not found."})
        body = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {"application/javascript", "application/json"}:
            content_type += "; charset=utf-8"
        self.send_response(200)
        self._headers(content_type, len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path.startswith("/api/"):
            self._api("GET")
        else:
            self._static_file()

    def do_POST(self):
        self._api("POST")

    def do_PATCH(self):
        self._api("PATCH")

    def do_DELETE(self):
        self._api("DELETE")


def create_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, data_dir: Path | str | None = None,
                  worker=None, ollama_client: OllamaClient | None = None) -> AccessSprintHTTPServer:
    if not _is_loopback_host(host):
        raise ValueError("AccessSprint can bind only to a loopback address.")
    data_dir = Path(data_dir) if data_dir is not None else default_data_dir()
    store = Store(data_dir / "accesssprint.sqlite3")
    server = AccessSprintHTTPServer((host, port), Handler)
    server.store = store
    server.audits = AuditService(store)
    server.scans = ScanService(store, worker=worker, work_dir=data_dir / "jobs")
    server.ollama_client = ollama_client
    return server

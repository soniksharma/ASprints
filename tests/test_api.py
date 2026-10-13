import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from accesssprint.server import create_server


class FakeOllama:
    def status(self):
        return {"available": False, "model_installed": False, "model": "gemma4:e4b",
                "message": "Start Ollama to enable local explanations."}
    def explain_finding(self, finding):
        return {"explanation": None, "raw_answer": None, "response_valid": False,
                "context_sent": {"rule_id": finding.get("rule_id")}, "model": "gemma4:e4b"}
    def test_connection(self):
        return {"available": False, "model": "gemma4:e4b", "message": "Offline"}


def fake_worker(payload, work_dir):
    return {"run_id": payload["runId"], "status": "completed", "axe_version": "4.14.0", "pages": [
        {"requested_url": url, "status": "ok", "final_url": url, "violations": [
            {"rule_id": "image-alt", "impact": "critical", "help": "Add alternative text",
             "description": "Images need text alternatives.", "help_url": "https://example.com/help",
             "nodes": [{"target": ["img"], "html": "<img src=photo>", "failure_summary": "No alt text"}],
             "passes": 2, "incomplete": 0}], "passes": 10, "incomplete": 0}
        for url in payload["pages"]]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.server = create_server("127.0.0.1", 0, data_dir=Path(self.temp_dir.name),
                                   worker=fake_worker, ollama_client=FakeOllama())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server.close_application()
        self.temp_dir.cleanup()

    def request(self, method, path, payload=None, raw=None):
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = Request(self.base + path, data=data, method=method,
                          headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with urlopen(request, timeout=5) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except HTTPError as error:
            body = error.read()
            return error.code, json.loads(body) if body else None

    def create_audit(self):
        status, body = self.request("POST", "/api/audits", {
            "name": "First audit", "client_name": "Northstar", "base_url": "https://example.com/",
            "auditor": "Sam", "scope": "Home page", "pages": [{"url": "https://example.com/", "label": "Home"}],
        })
        self.assertEqual(status, 201)
        return body["audit"]

    def test_health_reports_model_state_and_api_creates_audit(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertFalse(health["ollama"]["available"])
        audit = self.create_audit()
        status, detail = self.request("GET", f"/api/audits/{audit['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(detail["audit"]["name"], "First audit")

    def test_settings_keep_ollama_loopback_and_default_to_requested_model(self):
        status, settings = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertEqual(settings["settings"]["model"], "gemma4:e4b")
        status, _ = self.request("POST", "/api/settings", {"base_url": "http://example.com:11434", "model": "gemma4:e4b"})
        self.assertEqual(status, 400)
        status, saved = self.request("POST", "/api/settings", {"base_url": "http://127.0.0.1:11434", "model": "gemma4:e4b"})
        self.assertEqual(status, 200)
        self.assertEqual(saved["settings"]["model"], "gemma4:e4b")

    def test_ai_connection_test_endpoint(self):
        status, result = self.request("POST", "/api/ai/test", {})
        self.assertEqual(status, 200)
        self.assertFalse(result["test"]["available"])

    def test_rejects_malformed_and_oversized_json(self):
        status, _ = self.request("POST", "/api/audits", raw=b"{")
        self.assertEqual(status, 400)
        status, _ = self.request("POST", "/api/audits", raw=b" " * 1_000_001)
        self.assertEqual(status, 413)

    def test_scan_review_manual_check_archive_and_delete_endpoints(self):
        audit = self.create_audit()
        status, started = self.request("POST", f"/api/audits/{audit['id']}/scans", {})
        self.assertEqual(status, 202)
        scan_id = started["scan"]["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            status, scan = self.request("GET", f"/api/scans/{scan_id}")
            if scan["scan"]["status"] != "running":
                break
            time.sleep(0.02)
        self.assertEqual(scan["scan"]["status"], "completed")
        finding_id = scan["scan"]["findings"][0]["id"]
        status, explanation = self.request("POST", "/api/ai/explain", {"audit_id": audit["id"], "finding_id": finding_id})
        self.assertEqual(status, 200)
        self.assertEqual(explanation["result"]["context_sent"]["rule_id"], "image-alt")
        status, result = self.request("PATCH", f"/api/audits/{audit['id']}/findings/{finding_id}",
                                      {"status": "confirmed", "note": "Verified manually"})
        self.assertEqual(status, 200)
        self.assertEqual(result["finding"]["review_status"], "confirmed")
        check_id = audit["manual_checks"][0]["id"]
        status, result = self.request("PATCH", f"/api/audits/{audit['id']}/manual-checks/{check_id}",
                                      {"status": "pass", "note": "Keyboard order checked"})
        self.assertEqual(status, 200)
        self.assertEqual(result["manual_check"]["status"], "pass")
        status, second = self.request("POST", f"/api/audits/{audit['id']}/scans", {})
        self.assertEqual(status, 202)
        second_id = second["scan"]["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            _, second_result = self.request("GET", f"/api/scans/{second_id}")
            if second_result["scan"]["status"] != "running":
                break
            time.sleep(0.02)
        compare_path = f"/api/audits/{audit['id']}/scans/compare?baseline={scan_id}&current={second_id}"
        status, comparison = self.request("GET", compare_path)
        self.assertEqual(status, 200)
        self.assertEqual(comparison["comparison"]["current"]["total"], 1)
        status, _ = self.request("POST", f"/api/audits/{audit['id']}/archive", {"archived": True})
        self.assertEqual(status, 200)
        status, audits = self.request("GET", "/api/audits")
        self.assertEqual(status, 200)
        self.assertEqual(audits["audits"], [])
        status, _ = self.request("DELETE", f"/api/audits/{audit['id']}")
        self.assertEqual(status, 204)

    def test_rejects_non_loopback_bind_and_blocks_static_path_traversal(self):
        with self.assertRaises(ValueError):
            create_server("0.0.0.0", 0, data_dir=Path(self.temp_dir.name))
        status, _ = self.request("GET", "/../../README.md")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

import tempfile
import time
import unittest
from pathlib import Path

from accesssprint.audits import AuditService
from accesssprint.scans import ScanService
from accesssprint.store import Store


class ScanServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        self.temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=self.temp_root)
        self.store = Store(Path(self.temp_dir.name) / "accesssprint.sqlite3")
        self.audits = AuditService(self.store)
        self.audit = self.audits.create_audit({
            "name": "Test audit", "client_name": "Northstar", "base_url": "https://example.com",
            "auditor": "Sam", "scope": "Home and menu", "pages": [
                {"url": "https://example.com/", "label": "Home"},
                {"url": "https://example.com/menu", "label": "Menu"},
            ],
        })

    def tearDown(self):
        if hasattr(self, "scans"):
            self.scans.close()
        self.store.close()
        self.temp_dir.cleanup()

    def wait_for(self, scan_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            run = self.scans.get_scan(scan_id)
            if run["status"] != "running":
                return run
            time.sleep(0.02)
        self.fail("scan did not finish within five seconds")

    def test_persists_partial_page_failures_and_successful_findings(self):
        def worker(payload, work_dir):
            return {"run_id": payload["runId"], "status": "partial", "axe_version": "4.14.0", "pages": [
                {"requested_url": payload["pages"][0], "status": "ok", "final_url": payload["pages"][0],
                 "violations": [{"rule_id": "color-contrast", "impact": "serious", "help": "Fix contrast",
                                 "description": "Text needs sufficient contrast.", "help_url": "https://example.com/rule",
                                 "nodes": [{"target": ["main p"], "html": "<p>text</p>", "failure_summary": "Low contrast"}]}],
                 "passes": 5, "incomplete": 1},
                {"requested_url": payload["pages"][1], "status": "timeout", "error": "Timed out",
                 "violations": [], "passes": 0, "incomplete": 1},
            ]}
        self.scans = ScanService(self.store, worker=worker, work_dir=Path(self.temp_dir.name))
        started = self.scans.start_scan(self.audit["id"])
        result = self.wait_for(started["id"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual([page["status"] for page in result["result"]["pages"]], ["ok", "timeout"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule_id"], "color-contrast")
        self.assertEqual(result["findings"][0]["page_label"], "Home")

    def test_rejects_scan_for_unknown_audit(self):
        self.scans = ScanService(self.store, worker=lambda *_: {}, work_dir=Path(self.temp_dir.name))
        with self.assertRaises(ValueError):
            self.scans.start_scan("missing")

    def test_worker_command_is_a_shell_free_argument_list(self):
        from accesssprint.scans import run_worker
        seen = {}
        def fake_process(args, **kwargs):
            seen["args"] = args
            seen["kwargs"] = kwargs
            output_path = Path(args[-1])
            output_path.write_text('{"status":"completed","pages":[]}', encoding="utf-8")
            return type("Process", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        run_worker({"runId": "scan-1", "pages": ["https://example.com/"]}, Path(self.temp_dir.name),
                   process_runner=fake_process)
        self.assertIsInstance(seen["args"], list)
        self.assertFalse(seen["kwargs"]["shell"])


if __name__ == "__main__":
    unittest.main()

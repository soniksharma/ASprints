import unittest
import uuid
from pathlib import Path

from accesssprint.audits import AuditService
from accesssprint.reports import build_report, export_backup, import_backup, validate_backup
from accesssprint.store import Store


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(__file__).resolve().parents[1] / ".test-tmp" / f"{uuid.uuid4()}.sqlite3")
        self.audits = AuditService(self.store)
        self.audit = self.audits.create_audit({
            "name": "Review", "client_name": "<script>alert(1)</script>", "base_url": "https://example.com",
            "auditor": "Ari", "scope": "Public pages only",
            "pages": [{"url": "https://example.com", "label": "Home <b>"}],
        })

    def tearDown(self):
        path = self.store.path
        self.store.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(path) + suffix).unlink(missing_ok=True)

    def test_report_counts_coverage_and_states_certification_limit(self):
        report = build_report(self.audits.get_audit(self.audit["id"]))
        self.assertEqual(report["coverage"]["scanned"], 0)
        self.assertEqual(report["coverage"]["total"], 1)
        self.assertIn("not a certification", report["disclaimer"].lower())
        self.assertEqual(report["summary"]["manual_total"], 6)

    def test_report_escapes_user_content_in_print_html(self):
        from accesssprint.reports import render_report_html
        html = render_report_html(build_report(self.audits.get_audit(self.audit["id"])))
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>alert(1)</script>", html)

    def test_backup_round_trip_creates_a_new_audit_with_reviews(self):
        backup = export_backup(self.audits.get_audit(self.audit["id"]))
        checked = validate_backup(backup)
        imported = import_backup(self.audits, self.store, checked)
        self.assertNotEqual(imported["id"], self.audit["id"])
        self.assertEqual(imported["name"], self.audit["name"])
        self.assertEqual(len(imported["pages"]), 1)
        self.assertEqual(len(imported["manual_checks"]), 6)

    def test_backup_round_trip_preserves_scan_findings_and_manual_review(self):
        page = self.audit["pages"][0]
        scan_id = str(uuid.uuid4())
        self.store.create_scan_run({"id": scan_id, "audit_id": self.audit["id"], "status": "completed",
                                    "started_at": "2026-10-13T12:00:00Z", "result": {"pages": []}, "axe_version": "4.14.0"})
        self.store.create_finding({"id": str(uuid.uuid4()), "scan_id": scan_id, "page_id": page["id"],
                                   "rule_id": "image-alt", "impact": "critical", "help": "Add alt text",
                                   "description": "The image is missing an alternative.", "nodes": [],
                                   "review_status": "confirmed", "note": "Checked with a screen reader."})
        check = self.audit["manual_checks"][0]
        self.audits.set_manual_check(self.audit["id"], check["id"], "pass", "Keyboard order reviewed.")
        imported = import_backup(self.audits, self.store, validate_backup(export_backup(self.audits.get_audit(self.audit["id"]))))
        self.assertEqual(imported["scan_runs"][0]["status"], "completed")
        self.assertEqual(imported["findings"][0]["review_status"], "confirmed")
        self.assertEqual(imported["findings"][0]["note"], "Checked with a screen reader.")
        self.assertEqual(imported["manual_checks"][0]["note"], "Keyboard order reviewed.")

    def test_backup_rejects_unknown_version_and_malformed_records(self):
        with self.assertRaises(ValueError):
            validate_backup({"formatVersion": 99})
        with self.assertRaises(ValueError):
            validate_backup({"formatVersion": True})
        with self.assertRaises(ValueError):
            validate_backup({"formatVersion": 1, "audit": {"name": "x"}})


if __name__ == "__main__":
    unittest.main()

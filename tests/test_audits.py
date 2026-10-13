import tempfile
import unittest
from pathlib import Path

from accesssprint.audits import AuditError, AuditService
from accesssprint.store import Store


class AuditServiceTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=temp_root)
        self.store = Store(Path(self.temp_dir.name) / "accesssprint.sqlite3")
        self.audits = AuditService(self.store)
        self.payload = {
            "name": "Spring review", "client_name": "Northstar Cafe",
            "base_url": "https://example.com", "auditor": "Sam",
            "scope": "Public marketing pages", "pages": [
                {"url": "https://example.com", "label": "Home"},
                {"url": "https://example.com/menu", "label": "Menu"},
            ],
        }

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_creates_audit_with_pages_and_manual_checklist(self):
        audit = self.audits.create_audit(self.payload)
        self.assertEqual(audit["name"], "Spring review")
        self.assertEqual([p["label"] for p in audit["pages"]], ["Home", "Menu"])
        self.assertEqual(len(audit["manual_checks"]), 6)
        self.assertTrue(all(item["status"] == "not_checked" for item in audit["manual_checks"]))

    def test_rejects_missing_required_fields(self):
        with self.assertRaises(AuditError):
            self.audits.create_audit({"name": ""})

    def test_rejects_more_than_ten_pages(self):
        payload = dict(self.payload, pages=[{"url": f"https://example.com/{n}", "label": str(n)} for n in range(11)])
        with self.assertRaises(AuditError):
            self.audits.create_audit(payload)

    def test_rejects_audit_with_no_pages(self):
        with self.assertRaises(AuditError):
            self.audits.create_audit(dict(self.payload, pages=[]))

    def test_updates_and_archives_audit(self):
        audit = self.audits.create_audit(self.payload)
        updated = self.audits.update_audit(audit["id"], {"name": "May review", "scope": "Home only"})
        self.assertEqual(updated["name"], "May review")
        self.assertEqual(updated["scope"], "Home only")
        self.audits.archive_audit(audit["id"], True)
        self.assertEqual(self.audits.get_audit(audit["id"])["archived"], True)
        self.assertEqual(self.audits.list_audits(), [])

    def test_page_edits_preserve_previous_scan_evidence(self):
        audit = self.audits.create_audit(self.payload)
        self.store.create_scan_run({"id": "scan-old", "audit_id": audit["id"], "status": "completed",
                                    "started_at": "2026-10-12T00:00:00Z", "result": {}})
        self.store.create_finding({"id": "finding-old", "scan_id": "scan-old", "page_id": audit["pages"][0]["id"],
                                   "rule_id": "color-contrast", "impact": "serious", "help": "Fix contrast",
                                   "description": "Text must contrast", "nodes": []})
        self.audits.update_audit(audit["id"], {"pages": [{"url": "https://example.com/menu", "label": "Menu"}]})
        saved = self.audits.get_audit(audit["id"])
        self.assertEqual([page["label"] for page in saved["pages"]], ["Menu"])
        self.assertEqual(saved["findings"][0]["page_label"], "Home")

    def test_rejects_invalid_finding_status(self):
        audit = self.audits.create_audit(self.payload)
        self.store.create_scan_run({"id": "scan-a", "audit_id": audit["id"], "status": "completed",
                                    "started_at": "2026-10-13T00:00:00Z", "result": {}})
        self.store.create_finding({"id": "finding-a", "scan_id": "scan-a", "page_id": audit["pages"][0]["id"],
                                   "rule_id": "color-contrast", "impact": "serious", "help": "Fix contrast",
                                   "description": "Text must contrast", "nodes": []})
        with self.assertRaises(AuditError):
            self.audits.set_finding_review(audit["id"], "finding-a", "ignored", "")

    def test_updates_finding_and_manual_check_status_and_notes(self):
        audit = self.audits.create_audit(self.payload)
        self.store.create_scan_run({"id": "scan-a", "audit_id": audit["id"], "status": "completed",
                                    "started_at": "2026-10-13T00:00:00Z", "result": {}})
        self.store.create_finding({"id": "finding-a", "scan_id": "scan-a", "page_id": audit["pages"][0]["id"],
                                   "rule_id": "color-contrast", "impact": "serious", "help": "Fix contrast",
                                   "description": "Text must contrast", "nodes": []})
        finding = self.audits.set_finding_review(audit["id"], "finding-a", "confirmed", "Verified with zoom.")
        self.assertEqual((finding["review_status"], finding["note"]), ("confirmed", "Verified with zoom."))
        check = audit["manual_checks"][0]
        result = self.audits.set_manual_check(audit["id"], check["id"], "pass", "Tab order is logical.")
        self.assertEqual((result["status"], result["note"]), ("pass", "Tab order is logical."))

    def test_persists_audit_and_events_when_database_reopens(self):
        audit = self.audits.create_audit(self.payload)
        audit_id = audit["id"]
        self.store.close()
        self.store = Store(Path(self.temp_dir.name) / "accesssprint.sqlite3")
        self.audits = AuditService(self.store)
        persisted = self.audits.get_audit(audit_id)
        self.assertEqual(persisted["client_name"], "Northstar Cafe")
        self.assertGreaterEqual(len(persisted["events"]), 1)
        self.assertTrue(persisted["events"][0]["created_at"])

    def test_compares_scan_counts_by_impact_and_status(self):
        audit = self.audits.create_audit(self.payload)
        self.store.create_scan_run({"id": "scan-old", "audit_id": audit["id"], "status": "completed",
                                    "started_at": "2026-10-12T00:00:00Z", "result": {}})
        self.store.create_scan_run({"id": "scan-new", "audit_id": audit["id"], "status": "completed",
                                    "started_at": "2026-10-13T00:00:00Z", "result": {}})
        for scan_id, finding_id, status in (("scan-old", "old-a", "needs_review"),
                                            ("scan-new", "new-a", "fixed")):
            self.store.create_finding({"id": finding_id, "scan_id": scan_id, "page_id": audit["pages"][0]["id"],
                                       "rule_id": "color-contrast", "impact": "serious", "help": "Fix contrast",
                                       "description": "Text must contrast", "nodes": [], "review_status": status})
        result = self.audits.compare_scans(audit["id"], "scan-old", "scan-new")
        self.assertEqual(result["baseline"]["total"], 1)
        self.assertEqual(result["current"]["total"], 1)
        self.assertEqual(result["by_impact"]["serious"], {"before": 1, "after": 1})
        self.assertEqual(result["fixed"], 1)


if __name__ == "__main__":
    unittest.main()

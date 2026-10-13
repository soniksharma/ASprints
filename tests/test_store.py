import tempfile
import unittest
from pathlib import Path

from accesssprint.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".test-tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp_dir = tempfile.TemporaryDirectory(dir=temp_root)
        self.store = Store(Path(self.temp_dir.name) / "accesssprint.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp_dir.cleanup()

    def test_initializes_database_and_exposes_connection(self):
        self.assertTrue((Path(self.temp_dir.name) / "accesssprint.sqlite3").exists())
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_scan_run_payload_round_trips_as_json(self):
        self.store.create_audit(
            {"id": "audit-1", "name": "Site", "client_name": "Client",
             "base_url": "https://example.com", "auditor": "Me", "scope": "Home"},
            [{"id": "page-1", "url": "https://example.com", "label": "Home"}],
        )
        payload = {"pages": [{"url": "https://example.com", "status": "ok"}]}
        self.store.create_scan_run({
            "id": "scan-1", "audit_id": "audit-1", "status": "running",
            "started_at": "2026-10-13T00:00:00Z", "result": payload,
        })
        stored = self.store.get_scan_run("scan-1")
        self.assertEqual(stored["result"], payload)

    def test_audit_delete_cascades_to_child_rows(self):
        audit = {"id": "audit-1", "name": "Site", "client_name": "Client",
                 "base_url": "https://example.com", "auditor": "Me", "scope": "Home page"}
        self.store.create_audit(audit, [{"id": "page-1", "url": "https://example.com", "label": "Home"}])
        self.store.create_scan_run({"id": "scan-1", "audit_id": "audit-1", "status": "running",
                                    "started_at": "2026-10-13T00:00:00Z", "result": {}})
        self.store.delete_audit("audit-1")
        self.assertIsNone(self.store.get_audit("audit-1"))
        self.assertIsNone(self.store.get_scan_run("scan-1"))


if __name__ == "__main__":
    unittest.main()

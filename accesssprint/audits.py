"""Audit validation and user-facing operations."""

from __future__ import annotations

import uuid

from accesssprint.config import MAX_PAGES_PER_AUDIT
from accesssprint.store import Store, utc_now
from accesssprint.url_policy import UrlPolicyError, normalize_page_url


class AuditError(ValueError):
    """Raised for invalid audit input or an invalid audit operation."""


MANUAL_CHECKS = (
    ("keyboard_navigation", "Keyboard-only navigation"),
    ("visible_focus", "Visible keyboard focus"),
    ("page_structure", "Page title and heading structure"),
    ("forms_errors", "Form labels and error messages"),
    ("zoom_reflow", "Zoom and narrow-screen reflow"),
    ("screen_reader", "Screen-reader spot check"),
)
FINDING_STATUSES = {"needs_review", "confirmed", "fixed", "not_applicable"}
MANUAL_STATUSES = {"not_checked", "pass", "issue"}
TEXT_LIMITS = {"name": 120, "client_name": 120, "auditor": 120, "scope": 2000, "note": 4000}


class AuditService:
    def __init__(self, store: Store):
        self.store = store

    def _validate_text(self, value, field: str, *, required: bool = True) -> str:
        if not isinstance(value, str):
            raise AuditError(f"{field.replace('_', ' ').capitalize()} must be text.")
        value = value.strip()
        if required and not value:
            raise AuditError(f"{field.replace('_', ' ').capitalize()} is required.")
        if len(value) > TEXT_LIMITS.get(field, 4000):
            raise AuditError(f"{field.replace('_', ' ').capitalize()} is too long.")
        return value

    def _validate_pages(self, pages) -> list[dict]:
        if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES_PER_AUDIT:
            raise AuditError(f"Add between 1 and {MAX_PAGES_PER_AUDIT} pages to an audit.")
        normalized, seen = [], set()
        for page in pages:
            if not isinstance(page, dict):
                raise AuditError("Each page needs a URL and a short label.")
            try:
                url = normalize_page_url(page.get("url"))
            except UrlPolicyError as error:
                raise AuditError(str(error)) from error
            if url in seen:
                raise AuditError("Page URLs must be unique within an audit.")
            seen.add(url)
            label = self._validate_text(page.get("label", ""), "page label")
            if len(label) > 100:
                raise AuditError("Page labels must be 100 characters or fewer.")
            normalized.append({"id": str(uuid.uuid4()), "url": url, "label": label})
        return normalized

    def create_audit(self, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise AuditError("Audit details must be an object.")
        try:
            base_url = normalize_page_url(payload.get("base_url"))
        except UrlPolicyError as error:
            raise AuditError(str(error)) from error
        pages = self._validate_pages(payload.get("pages"))
        audit = {
            "id": str(uuid.uuid4()),
            "name": self._validate_text(payload.get("name"), "name"),
            "client_name": self._validate_text(payload.get("client_name"), "client_name"),
            "base_url": base_url,
            "auditor": self._validate_text(payload.get("auditor"), "auditor"),
            "scope": self._validate_text(payload.get("scope"), "scope"),
            "created_at": utc_now(),
        }
        checks = [{"id": str(uuid.uuid4()), "key": key, "label": label} for key, label in MANUAL_CHECKS]
        self.store.create_audit(audit, pages, checks)
        return self.get_audit(audit["id"])

    def get_audit(self, audit_id: str) -> dict:
        audit = self.store.get_audit(audit_id)
        if audit is None:
            raise AuditError("Audit not found.")
        return audit

    def list_audits(self) -> list[dict]:
        return self.store.list_audits()

    def update_audit(self, audit_id: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise AuditError("Audit changes must be an object.")
        allowed = {"name", "client_name", "base_url", "auditor", "scope"}
        fields = {}
        for key in allowed.intersection(payload):
            if key == "base_url":
                try:
                    fields[key] = normalize_page_url(payload[key])
                except UrlPolicyError as error:
                    raise AuditError(str(error)) from error
            else:
                fields[key] = self._validate_text(payload[key], key)
        pages = self._validate_pages(payload["pages"]) if "pages" in payload else None
        if not fields and pages is None:
            raise AuditError("No editable audit fields were provided.")
        if not self.store.update_audit(audit_id, fields, pages):
            raise AuditError("Audit not found.")
        return self.get_audit(audit_id)

    def archive_audit(self, audit_id: str, archived: bool) -> None:
        if not isinstance(archived, bool):
            raise AuditError("Archive state must be true or false.")
        if not self.store.archive_audit(audit_id, archived):
            raise AuditError("Audit not found.")

    def delete_audit(self, audit_id: str) -> None:
        if not self.store.delete_audit(audit_id):
            raise AuditError("Audit not found.")

    def set_finding_review(self, audit_id: str, finding_id: str, status: str, note: str) -> dict:
        if status not in FINDING_STATUSES:
            raise AuditError("Choose a valid finding review status.")
        note = self._validate_text(note, "note", required=False)
        finding = self.store.get_finding(finding_id, audit_id)
        if finding is None:
            raise AuditError("Finding not found in this audit.")
        self.store.update_finding(finding_id, review_status=status, note=note)
        self.store.add_event(audit_id, "finding_review_updated", {"finding_id": finding_id, "status": status})
        return self.store.get_finding(finding_id, audit_id)

    def set_manual_check(self, audit_id: str, check_id: str, status: str, note: str) -> dict:
        if status not in MANUAL_STATUSES:
            raise AuditError("Choose a valid manual check status.")
        note = self._validate_text(note, "note", required=False)
        check = self.store.get_manual_check(check_id, audit_id)
        if check is None:
            raise AuditError("Manual check not found in this audit.")
        self.store.update_manual_check(check_id, status=status, note=note)
        self.store.add_event(audit_id, "manual_check_updated", {"check_id": check_id, "status": status})
        return self.store.get_manual_check(check_id, audit_id)

    def compare_scans(self, audit_id: str, baseline_id: str, current_id: str) -> dict:
        audit = self.get_audit(audit_id)
        runs = {run["id"]: run for run in audit["scan_runs"]}
        if baseline_id not in runs or current_id not in runs or baseline_id == current_id:
            raise AuditError("Choose two different scans from this audit to compare.")
        before = self.store.list_findings(audit_id, baseline_id)
        after = self.store.list_findings(audit_id, current_id)
        by_impact = {}
        for impact in ("critical", "serious", "moderate", "minor", "unknown"):
            by_impact[impact] = {
                "before": sum(item["impact"] == impact for item in before),
                "after": sum(item["impact"] == impact for item in after),
            }
        before_keys = {(x["rule_id"], x["page_url"], n.get("target", ""))
                       for x in before for n in x["nodes"]}
        after_keys = {(x["rule_id"], x["page_url"], n.get("target", ""))
                      for x in after for n in x["nodes"]}
        return {
            "audit_id": audit_id,
            "baseline": {"id": baseline_id, "started_at": runs[baseline_id]["started_at"], "total": len(before)},
            "current": {"id": current_id, "started_at": runs[current_id]["started_at"], "total": len(after)},
            "by_impact": by_impact,
            "new": len(after_keys - before_keys),
            "resolved": len(before_keys - after_keys),
            "fixed": sum(item["review_status"] == "fixed" for item in after),
        }

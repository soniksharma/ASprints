"""Clearly labeled, offline sample data for first-run exploration."""

import uuid

from accesssprint.audits import AuditService
from accesssprint.store import Store, utc_now


def ensure_demo_data(store: Store) -> None:
    if store.list_audits(include_archived=True):
        return
    audits = AuditService(store)
    audit = audits.create_audit({
        "name": "DEMO // Northstar Cafe",
        "client_name": "Northstar Cafe · sample",
        "base_url": "https://northstar.example/",
        "auditor": "AccessSprint demo",
        "scope": "Sample homepage and menu. These are illustrative findings, not a real scan.",
        "pages": [
            {"url": "https://northstar.example/", "label": "Homepage"},
            {"url": "https://northstar.example/menu", "label": "Menu"},
        ],
    })
    store.mark_demo(audit["id"])
    scan_id = str(uuid.uuid4())
    started_at = utc_now()
    pages = audit["pages"]
    store.create_scan_run({
        "id": scan_id, "audit_id": audit["id"], "status": "completed", "started_at": started_at,
        "completed_at": started_at, "axe_version": "4.14.0", "model_tag": "demo only",
        "result": {"sample": True, "status": "completed", "axe_version": "4.14.0", "pages": [
            {"requested_url": page["url"], "final_url": page["url"], "status": "ok", "sample": True,
             "passes": 24 - index * 3, "incomplete": 1,
             "violations": [{"rule_id": rule, "impact": impact} for rule, impact in (
                 ("image-alt", "serious"), ("color-contrast", "serious"), ("link-name", "moderate"),
             )] if index == 0 else [{"rule_id": "heading-order", "impact": "moderate"}],
            } for index, page in enumerate(pages)]},
    })
    sample_findings = [
        {"rule_id": "image-alt", "impact": "serious", "help": "Images need alternative text",
         "description": "Informative images need a text alternative that communicates their purpose.",
         "nodes": [{"target": ["main img.hero"], "html": "<img class=\"hero\" src=\"/pastries.jpg\">",
                    "failure_summary": "No alt attribute was found for this image."}]},
        {"rule_id": "color-contrast", "impact": "serious", "help": "Text needs sufficient contrast",
         "description": "Text needs enough contrast against its background to remain readable.",
         "nodes": [{"target": [".menu-price"], "html": "<span class=\"menu-price\">$8</span>",
                    "failure_summary": "The foreground and background colors do not meet the minimum contrast ratio."}]},
        {"rule_id": "link-name", "impact": "moderate", "help": "Links need an accessible name",
         "description": "A link needs a name that communicates its destination or purpose.",
         "nodes": [{"target": ["a.social-link"], "html": "<a class=\"social-link\"><svg>…</svg></a>",
                    "failure_summary": "This icon-only link has no accessible name."}]},
        {"rule_id": "heading-order", "impact": "moderate", "help": "Headings should follow a logical order",
         "description": "Heading levels should not skip in a way that obscures the page outline.",
         "nodes": [{"target": ["main h4"], "html": "<h4>Our menu</h4>",
                    "failure_summary": "The heading level jumps from h1 to h4."}]},
    ]
    for index, finding in enumerate(sample_findings):
        store.create_finding({**finding, "id": str(uuid.uuid4()), "scan_id": scan_id,
                              "page_id": pages[0 if index < 3 else 1]["id"],
                              "review_status": "needs_review" if index != 1 else "confirmed",
                              "note": "Sample reviewer note" if index == 1 else ""})
    for check in audit["manual_checks"]:
        if check["check_key"] == "keyboard_navigation":
            store.update_manual_check(check["id"], status="pass", note="Sample: every item is reachable with Tab.")
        elif check["check_key"] == "visible_focus":
            store.update_manual_check(check["id"], status="issue", note="Sample: focus is difficult to see on the menu.")

"""Client-facing report construction and portable, validated audit backups."""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timezone

from accesssprint.audits import AuditService, FINDING_STATUSES, MANUAL_STATUSES, MANUAL_CHECKS
from accesssprint.store import Store, utc_now

BACKUP_VERSION = 1
IMPACTS = {"critical", "serious", "moderate", "minor", "unknown"}
SCAN_STATUSES = {"running", "completed", "partial", "failed"}


def build_report(audit: dict) -> dict:
    latest = audit["scan_runs"][0] if audit.get("scan_runs") else None
    page_results = {item.get("requested_url"): item for item in (latest or {}).get("result", {}).get("pages", [])}
    pages = [{"label": page["label"], "url": page["url"],
              "status": page_results.get(page["url"], {}).get("status", "not scanned")}
             for page in audit.get("pages", [])]
    findings = [item for item in audit.get("findings", []) if latest is None or item["scan_id"] == latest["id"]]
    checks = audit.get("manual_checks", [])
    return {
        "formatVersion": 1, "generated_at": datetime.now(timezone.utc).date().isoformat(),
        "title": "Accessibility review", "audit_name": audit["name"], "client_name": audit["client_name"],
        "auditor": audit["auditor"], "scope": audit["scope"], "demo": bool(audit.get("demo")),
        "coverage": {"scanned": sum(page["status"] == "ok" for page in pages), "total": len(pages), "pages": pages},
        "summary": {"findings": len(findings), "unreviewed": sum(item["review_status"] == "needs_review" for item in findings),
                    "manual_completed": sum(item["status"] != "not_checked" for item in checks), "manual_total": len(checks),
                    "unresolved_high_priority": sum(item["impact"] in {"critical", "serious"} and item["review_status"] not in {"fixed", "not_applicable"} for item in findings),
                    "by_impact": {impact: sum(item["impact"] == impact for item in findings) for impact in sorted(IMPACTS)}},
        "findings": findings, "manual_checks": checks,
        "disclaimer": "This report summarizes automated scanner evidence and human observations for the stated scope. It is not a certification, legal opinion, or guarantee of accessibility.",
        "limitations": ["Automated checks cover only a subset of accessibility requirements.",
                        "Results apply to the listed pages and the time of the recorded scan.",
                        "A qualified human should review each finding and test key workflows."],
        "tools": {"axe_core": latest.get("axe_version") if latest else "Not run", "browser": "Local Chromium", "model": latest.get("model_tag") or "Not used" if latest else "Not used"},
    }


def render_report_html(report: dict) -> str:
    e = lambda value: html.escape(str(value or ""), quote=True)
    page_rows = "".join(f"<tr><td>{e(p['label'])}</td><td>{e(p['url'])}</td><td>{e(p['status'])}</td></tr>" for p in report["coverage"]["pages"])
    finding_rows = "".join(f"<article><h3>{e(f['help'])}</h3><p>{e(f['impact'])} · {e(f['page_label'])} · {e(f['rule_id'])} · {e(f['review_status'].replace('_', ' '))}</p><p>{e(f['description'])}</p>{'<p>Auditor note: ' + e(f['note']) + '</p>' if f.get('note') else ''}</article>" for f in report["findings"])
    check_rows = "".join(f"<li>{e(c['label'])}: {e(c['status'].replace('_', ' '))}{' — ' + e(c['note']) if c.get('note') else ''}</li>" for c in report["manual_checks"])
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{e(report['client_name'])} accessibility review</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#18221b}}h1,h2{{line-height:1.2}}small,footer{{color:#526057}}article,.metrics{{border:1px solid #cbd4cc;padding:14px;margin:12px 0}}.metrics{{display:flex;justify-content:space-around}}@media print{{body{{margin:0;max-width:none}}}}</style>
<header><p>ACCESSIBILITY REVIEW / HUMAN-REVIEWED</p><h1>{e(report['client_name'])}</h1><h2>{e(report['audit_name'])}</h2><p>{e(report['scope'])}</p><p>Prepared by {e(report['auditor'])} · {e(report['generated_at'])}</p></header>
<section class="metrics"><div>{report['coverage']['scanned']}/{report['coverage']['total']} pages scanned</div><div>{report['summary']['findings']} findings</div><div>{report['summary']['unreviewed']} awaiting review</div><div>{report['summary']['unresolved_high_priority']} unresolved high priority</div></section>
<h2>Page coverage</h2><table><thead><tr><th>Page</th><th>URL</th><th>Status</th></tr></thead><tbody>{page_rows}</tbody></table><h2>Findings for review</h2>{finding_rows or '<p>No automated findings recorded.</p>'}<h2>Hands-on checks</h2><ul>{check_rows}</ul><footer><p>{e(report['disclaimer'])}</p><ul>{''.join('<li>'+e(item)+'</li>' for item in report['limitations'])}</ul></footer></html>"""


def export_backup(audit: dict) -> dict:
    return {"formatVersion": BACKUP_VERSION, "exported_at": utc_now(), "audit": {
        "name": audit["name"], "client_name": audit["client_name"], "base_url": audit["base_url"],
        "auditor": audit["auditor"], "scope": audit["scope"], "demo": bool(audit.get("demo")),
        "pages": [{key: page[key] for key in ("url", "label")} for page in audit["pages"]],
        "manual_checks": [{key: item[key] for key in ("check_key", "status", "note")} for item in audit["manual_checks"]],
        "scan_runs": [{key: run.get(key) for key in ("id", "status", "started_at", "completed_at", "axe_version", "model_tag", "result")} for run in audit["scan_runs"]],
        "findings": [{key: item.get(key) for key in ("scan_id", "page_url", "rule_id", "impact", "help", "description", "help_url", "nodes", "review_status", "note", "created_at")} for item in audit["findings"]],
    }}


def validate_backup(payload: dict) -> dict:
    if not isinstance(payload, dict) or type(payload.get("formatVersion")) is not int or payload.get("formatVersion") != BACKUP_VERSION:
        raise ValueError("This backup version is not supported.")
    audit = payload.get("audit")
    required = {"name", "client_name", "base_url", "auditor", "scope", "pages", "manual_checks", "scan_runs", "findings"}
    if not isinstance(audit, dict) or not required.issubset(audit):
        raise ValueError("Backup audit data is incomplete.")
    if any(not isinstance(audit.get(key), str) or len(audit[key]) > limit for key, limit in
           (("name", 120), ("client_name", 120), ("base_url", 2048), ("auditor", 120), ("scope", 2000))):
        raise ValueError("Backup audit details are invalid.")
    pages = audit["pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= 10 or any(
        not isinstance(p, dict) or not isinstance(p.get("url"), str) or len(p["url"]) > 2048
        or not isinstance(p.get("label"), str) or not 1 <= len(p["label"]) <= 100 for p in pages
    ):
        raise ValueError("Backup pages are invalid.")
    checks = audit["manual_checks"]
    valid_keys = {key for key, _ in MANUAL_CHECKS}
    if not isinstance(checks, list) or len(checks) > 20 or any(
        not isinstance(c, dict) or c.get("check_key") not in valid_keys or c.get("status") not in MANUAL_STATUSES
        or not isinstance(c.get("note", ""), str) or len(c.get("note", "")) > 4000 for c in checks
    ):
        raise ValueError("Backup manual checks are invalid.")
    runs = audit["scan_runs"]
    if not isinstance(runs, list) or len(runs) > 500 or any(
        not isinstance(r, dict) or r.get("status") not in SCAN_STATUSES or not isinstance(r.get("id"), str)
        or not isinstance(r.get("result"), dict) or not isinstance(r.get("started_at"), str)
        or any(r.get(key) is not None and not isinstance(r.get(key), str) for key in ("completed_at", "axe_version", "model_tag"))
        or not isinstance(r["result"].get("pages", []), list) or len(r["result"].get("pages", [])) > 10
        or any(not isinstance(page, dict) or page.get("status") not in {"ok", "timeout", "blocked", "error"}
               for page in r["result"].get("pages", [])) for r in runs
    ):
        raise ValueError("Backup scans are invalid.")
    run_ids = [run.get("id") for run in runs]
    if any(not isinstance(item, str) for item in run_ids) or len(set(run_ids)) != len(run_ids):
        raise ValueError("Backup scan identifiers are invalid.")
    page_urls = {page["url"] for page in pages}
    findings = audit["findings"]
    if not isinstance(findings, list) or len(findings) > 10000:
        raise ValueError("Backup findings are invalid.")
    for finding in findings:
        if (not isinstance(finding, dict) or finding.get("scan_id") not in run_ids
                or finding.get("page_url") not in page_urls or not isinstance(finding.get("rule_id"), str)
                or len(finding.get("rule_id", "")) > 100
                or finding.get("impact") not in IMPACTS or finding.get("review_status") not in FINDING_STATUSES
                or not isinstance(finding.get("nodes"), list) or len(finding["nodes"]) > 25
                or any(not isinstance(node, dict) or not isinstance(node.get("target", []), list)
                       or len(node.get("target", [])) > 5
                       or any(not isinstance(item, str) or len(item) > 300 for item in node.get("target", []))
                       or any(not isinstance(node.get(key, ""), str) or len(node.get(key, "")) > limit
                              for key, limit in (("html", 400), ("failure_summary", 1600)))
                       for node in finding["nodes"])
                or any(not isinstance(finding.get(key, ""), str) for key in ("help", "description", "help_url", "note"))):
            raise ValueError("Backup finding fields are invalid.")
        if any(len(finding.get(key, "")) > limit for key, limit in
               (("help", 300), ("description", 1200), ("help_url", 500), ("note", 4000))):
            raise ValueError("Backup finding text is too long.")
    return {"formatVersion": BACKUP_VERSION, "audit": audit}


def import_backup(audits: AuditService, store: Store, payload: dict) -> dict:
    audit = payload["audit"]
    created = audits.create_audit({key: audit[key] for key in ("name", "client_name", "base_url", "auditor", "scope", "pages")})
    store.set_demo(created["id"], False)
    page_by_url = {page["url"]: page for page in created["pages"]}
    for check in audit["manual_checks"]:
        match = next((item for item in created["manual_checks"] if item["check_key"] == check["check_key"]), None)
        if match:
            audits.set_manual_check(created["id"], match["id"], check["status"], check.get("note", ""))
    run_ids = {}
    for index, run in enumerate(audit["scan_runs"]):
        new_id = str(uuid.uuid4()); run_ids[run.get("id", str(index))] = new_id
        run_status = "failed" if run["status"] == "running" else run["status"]
        result = run["result"]
        if run["status"] == "running":
            result = {**result, "status": "failed", "import_note": "The backup was taken while this scan was still running."}
        store.create_scan_run({"id": new_id, "audit_id": created["id"], "status": run_status,
                               "started_at": run.get("started_at") or utc_now(), "completed_at": run.get("completed_at"),
                               "axe_version": run.get("axe_version"), "model_tag": run.get("model_tag"), "result": result})
    for item in audit["findings"]:
        page = page_by_url.get(item.get("page_url"))
        scan_id = run_ids.get(item.get("scan_id"))
        if not page or not scan_id:
            continue
        store.create_finding({"id": str(uuid.uuid4()), "scan_id": scan_id, "page_id": page["id"], "rule_id": item["rule_id"],
                              "impact": item["impact"], "help": item.get("help", ""), "description": item.get("description", ""),
                              "help_url": item.get("help_url", ""), "nodes": item["nodes"], "review_status": item["review_status"],
                              "note": item.get("note", ""), "created_at": item.get("created_at") or utc_now()})
    return audits.get_audit(created["id"])

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

export function filterFindings(findings = [], filters = {}) {
  const { impact = "all", status = "all", query = "" } = filters;
  const term = String(query).trim().toLowerCase();
  return findings.filter(finding => {
    if (impact !== "all" && finding.impact !== impact) return false;
    if (status !== "all" && finding.review_status !== status) return false;
    if (!term) return true;
    const haystack = [finding.rule_id, finding.help, finding.description, finding.page_url,
      finding.page_label, finding.impact].join(" ").toLowerCase();
    return haystack.includes(term);
  });
}

export function summarizeAudit(audit = {}) {
  const scans = Array.isArray(audit.scan_runs) ? audit.scan_runs : [];
  const latestScan = scans[0] || null;
  const findings = (Array.isArray(audit.findings) ? audit.findings : []).filter(item =>
    !latestScan || item.scan_id === latestScan.id);
  const manualChecks = Array.isArray(audit.manual_checks) ? audit.manual_checks : [];
  return {
    latestScan,
    totalFindings: findings.length,
    highPriority: findings.filter(item => ["critical", "serious"].includes(item.impact)
      && !["fixed", "not_applicable"].includes(item.review_status)).length,
    reviewed: findings.filter(item => item.review_status && item.review_status !== "needs_review").length,
    manualCompleted: manualChecks.filter(item => item.status && item.status !== "not_checked").length,
    manualTotal: manualChecks.length,
  };
}

export function formatDate(value) {
  if (!value) return "Not run";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }).format(date);
}

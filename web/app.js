import { api, ApiError } from "./api.js";
import { escapeHtml, filterFindings, formatDate, summarizeAudit } from "./view-model.js";

const app = document.querySelector("#main-content");
const toast = document.querySelector("#toast");
const dialog = document.querySelector("#audit-dialog");
const state = {
  screen: "dashboard", tab: "overview", audits: [], archivedAudits: [], details: new Map(), audit: null,
  health: null, settings: { base_url: "http://127.0.0.1:11434", model: "gemma4:e4b" },
  filter: { impact: "all", status: "all", query: "" }, selectedFindingId: null,
  explanations: {}, explanationBusy: false, compare: null, error: "", scanBusy: false,
  editingAuditId: null,
};
let toastTimer;
let scanTimer;

const e = escapeHtml;
const tabNames = [
  ["overview", "Overview"], ["findings", "Findings"], ["manual", "Manual checks"],
  ["compare", "Scan diff"], ["report", "Client report"],
];
const checkHelp = {
  keyboard_navigation: "Can you reach and operate the main actions with Tab, Shift+Tab, Enter, and Space?",
  visible_focus: "Is the current keyboard position always easy to see?",
  page_structure: "Does the page title describe the page, and do headings form a useful outline?",
  forms_errors: "Do fields have clear labels, and are errors explained and connected to the field?",
  zoom_reflow: "Does content remain usable at 200% zoom and on a narrow viewport?",
  screen_reader: "Spot-check a key flow with a screen reader and note anything it misses.",
};

function toastMessage(message, isError = false) {
  toast.textContent = message;
  toast.classList.toggle("is-error", isError);
  toast.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("is-visible"), 3600);
}

function impactClass(impact) {
  return `impact-${["critical", "serious", "moderate", "minor"].includes(impact) ? impact : "unknown"}`;
}

function statusBadge(status) {
  const statusMap = {
    completed: ["badge-good", "COMPLETE"], partial: ["badge-warn", "PARTIAL"],
    failed: ["badge-bad", "FAILED"], running: ["badge-neutral", "RUNNING"],
    not_checked: ["badge-neutral", "NOT CHECKED"], pass: ["badge-good", "PASS"],
    issue: ["badge-warn", "ISSUE"], needs_review: ["badge-neutral", "NEEDS REVIEW"],
    confirmed: ["badge-good", "CONFIRMED"], fixed: ["badge-good", "FIXED"],
    not_applicable: ["badge-neutral", "NOT APPLICABLE"],
  };
  const [className, label] = statusMap[status] || ["badge-neutral", String(status || "UNKNOWN").toUpperCase()];
  return `<span class="badge ${className}">${e(label)}</span>`;
}

function updateModelIndicator() {
  const indicator = document.querySelector("#model-indicator");
  const ollama = state.health?.ollama;
  let className = "status-unknown";
  let label = "CHECKING LOCAL MODEL";
  if (ollama?.available && ollama.model_installed) {
    className = "status-ready";
    label = `${ollama.model} / READY`;
  } else if (ollama?.available) {
    className = "status-unknown";
    label = `${ollama.model} / PULL MODEL`;
  } else if (ollama) {
    className = "status-offline";
    label = "OLLAMA OFFLINE";
  }
  indicator.innerHTML = `<i class="status-dot ${className}" aria-hidden="true"></i><span>${e(label)}</span>`;
}

function setCrumb(value) {
  document.querySelector("#crumb-current").textContent = value.toUpperCase();
  document.querySelectorAll(".rail-link").forEach(link => {
    const action = link.dataset.action;
    link.classList.toggle("is-active", (state.screen === "dashboard" && action === "dashboard")
      || (state.screen === "settings" && action === "settings"));
  });
  updateModelIndicator();
}

function renderError(title, message, action = "dashboard") {
  app.innerHTML = `<section class="empty-state" role="alert"><span class="empty-glyph">!</span><h2>${e(title)}</h2><p>${e(message)}</p><button class="button button-secondary" data-action="${e(action)}">${action === "dashboard" ? "BACK TO AUDITS" : "RETRY"}</button></section>`;
}

async function refreshDashboard() {
  const allAudits = await api.listAudits({ includeArchived: true });
  state.audits = allAudits.filter(audit => !audit.archived);
  state.archivedAudits = allAudits.filter(audit => audit.archived);
  const entries = await Promise.all(state.audits.map(async audit => {
    try { return await api.getAudit(audit.id); } catch { return audit; }
  }));
  state.details = new Map(entries.map(audit => [audit.id, audit]));
}

function renderAuditCard(audit) {
  const summary = summarizeAudit(state.details.get(audit.id) || audit);
  const clientLabel = audit.demo ? "SAMPLE PROJECT" : e(audit.client_name);
  const label = audit.demo ? `<span class="badge badge-demo">DEMO / SAMPLE</span>` : statusBadge(summary.latestScan?.status || "not_checked");
  return `<article class="audit-card">
    <div class="audit-card-top"><div class="audit-copy"><span class="eyebrow">${clientLabel}</span><h3>${e(audit.name)}</h3><p class="audit-url">${e(audit.base_url)}</p></div>${label}</div>
    <div class="audit-card-bottom"><div class="audit-metrics"><div class="metric-inline"><strong class="${summary.highPriority ? "impact-serious" : ""}">${summary.highPriority}</strong><span>high priority</span></div><div class="metric-inline"><strong>${summary.manualCompleted}/${summary.manualTotal}</strong><span>manual checks</span></div><div class="metric-inline"><strong>${summary.totalFindings}</strong><span>latest findings</span></div></div><button class="audit-open" data-action="open-audit" data-id="${e(audit.id)}">OPEN AUDIT <span aria-hidden="true">↗</span></button></div>
  </article>`;
}

function renderArchivedCard(audit) {
  return `<article class="audit-card archived-card"><div class="audit-card-top"><div class="audit-copy"><span class="eyebrow">ARCHIVED PROJECT</span><h3>${e(audit.name)}</h3><p class="audit-url">${e(audit.client_name)} · ${e(audit.base_url)}</p></div><span class="badge badge-neutral">PAUSED</span></div><div class="audit-card-bottom"><span class="muted small">Saved locally · ${e(formatDate(audit.updated_at))}</span><button class="button button-secondary" data-action="restore-audit" data-id="${e(audit.id)}">RESTORE</button></div></article>`;
}

function renderDashboard() {
  state.screen = "dashboard";
  setCrumb("Audit desk");
  const realCount = state.audits.filter(audit => !audit.demo).length;
  const demo = state.audits.find(audit => audit.demo);
  app.innerHTML = `<section class="hero-panel">
    <div class="hero-copy"><span class="eyebrow">PRIVATE BY DEFAULT / GEMMA ON DEVICE</span>
      <h1>Make the web easier to use.<br><em>Make your work easier to sell.</em></h1>
      <p class="lede">Turn a small website review into a clear, human-checked action plan your client can actually use.</p>
      <div class="hero-actions"><button class="button button-primary" data-action="new-audit">START A CLIENT AUDIT <span aria-hidden="true">↗</span></button><button class="button button-secondary" data-action="import-backup-file">RESTORE JSON BACKUP</button><input id="backup-file" class="visually-hidden" type="file" accept="application/json,.json" aria-label="Choose an AccessSprint JSON backup">${demo ? `<button class="button button-secondary" data-action="open-audit" data-id="${e(demo.id)}">EXPLORE THE SAMPLE <span aria-hidden="true">⌁</span></button>` : ""}</div>
    </div>
    <div class="terminal-card" aria-label="AccessSprint local system status">
      <div class="terminal-head"><span class="terminal-dots"><i></i><i></i><i></i></span><span>AS / SYSTEM CHECK</span><span>01</span></div>
      <div class="terminal-line"><strong>&gt;</strong><span>scanner <span class="terminal-ok">ready</span></span></div>
      <div class="terminal-line"><strong>&gt;</strong><span>storage <span class="terminal-ok">local.sqlite</span></span></div>
      <div class="terminal-line"><strong>&gt;</strong><span>model <span class="${state.health?.ollama?.model_installed ? "terminal-ok" : ""}">${e(state.health?.ollama?.model || "gemma4:e4b")}</span></span></div>
      <div class="terminal-line"><strong>&gt;</strong><span>client data stays on this device<span class="terminal-cursor" aria-hidden="true"></span></span></div>
    </div>
  </section>
  <div class="section-row"><div><h2>Your audit desk</h2><span class="section-meta">${realCount.toString().padStart(2, "0")} REAL PROJECT${realCount === 1 ? "" : "S"} / ${state.audits.length.toString().padStart(2, "0")} TOTAL</span></div><button class="button button-quiet" data-action="settings">MODEL SETUP <span aria-hidden="true">⌘</span></button></div>
  ${state.audits.length ? `<div class="audit-grid">${state.audits.map(renderAuditCard).join("")}</div>` : `<div class="empty-state"><span class="empty-glyph">A//</span><h2>No audits yet</h2><p>Create a small, permission-based scope. Your first client report starts with a few explicit pages.</p><button class="button button-primary" data-action="new-audit">CREATE FIRST AUDIT</button></div>`}
  ${state.archivedAudits.length ? `<div class="section-row"><h2>Archived / restore anytime</h2><span class="section-meta">${state.archivedAudits.length} SAVED</span></div><div class="audit-grid">${state.archivedAudits.map(renderArchivedCard).join("")}</div>` : ""}
  <div class="section-row"><h2>How a sprint works</h2><span class="section-meta">SCAN → REVIEW → DELIVER</span></div>
  <div class="audit-grid workflow-grid">
    <div class="panel panel-pad"><span class="eyebrow">01 / COLLECT EVIDENCE</span><h3 class="space-before-small">Scan a bounded set of pages</h3><p class="muted small">Local Chromium runs axe-core. Every result stays attached to the page and element that triggered it.</p></div>
    <div class="panel panel-pad"><span class="eyebrow">02 / USE YOUR JUDGMENT</span><h3 class="space-before-small">Review, then explain</h3><p class="muted small">Confirm findings yourself. Local Gemma translates scanner evidence into a practical fix and a way to verify it.</p></div>
  </div>`;
}

function auditHeader(audit, summary) {
  return `<div class="page-head"><div><span class="eyebrow">${audit.demo ? "SAMPLE DATA / ILLUSTRATIVE ONLY" : "CLIENT REVIEW / LOCAL RUN"}</span><h1>${e(audit.name)}</h1><p class="lede">${e(audit.scope)}</p></div><div class="page-head-actions">${!audit.demo ? `<button class="button button-quiet" data-action="edit-audit">EDIT SCOPE</button><button class="button button-danger" data-action="delete-audit">DELETE</button><button class="button button-quiet" data-action="archive-audit">ARCHIVE</button>` : ""}<button class="button button-primary" data-action="start-scan" ${audit.demo ? "disabled title='Create a real audit to run a live scan.'" : ""}>
    ${state.scanBusy ? "SCANNING…" : "RUN ACCESSIBILITY SCAN"} <span aria-hidden="true">⟶</span></button></div></div>
    <div class="audit-tabs" role="tablist" aria-label="Audit sections">${tabNames.map(([key, label]) => `<button role="tab" aria-selected="${state.tab === key}" class="tab-button ${state.tab === key ? "is-active" : ""}" data-tab="${key}">${e(label)}</button>`).join("")}</div>`;
}

function renderStats(audit) {
  const summary = summarizeAudit(audit);
  return `<div class="stat-strip">
    <div class="stat-card ${summary.highPriority ? "is-hot" : "is-good"}"><span>High priority</span><strong>${summary.highPriority.toString().padStart(2, "0")}</strong><small>Open critical or serious findings</small></div>
    <div class="stat-card"><span>Latest scan</span><strong class="stat-status">${e((summary.latestScan?.status || "not run").toUpperCase())}</strong><small>${e(formatDate(summary.latestScan?.started_at))}</small></div>
    <div class="stat-card is-good"><span>Reviewed</span><strong>${summary.reviewed}/${summary.totalFindings}</strong><small>Human-reviewed latest findings</small></div>
    <div class="stat-card"><span>Manual checks</span><strong>${summary.manualCompleted}/${summary.manualTotal}</strong><small>Document your hands-on review</small></div>
  </div>`;
}

function renderSampleBanner(audit) {
  return audit.demo ? `<div class="sample-banner"><span aria-hidden="true">ⓘ</span><div><strong>SAMPLE DATA</strong> These findings are illustrative examples. No live site was scanned. Create a client audit to run your own review.</div></div>` : "";
}

function renderScanLog(audit) {
  const scan = audit.scan_runs?.[0];
  if (!scan) return `<div class="run-log"><div class="run-log-head"><span>LAST RUN / NONE</span><span>READY</span></div><div class="run-log-line"><span>01</span><span>No pages scanned yet. Start with a small, permission-based scope.</span></div></div>`;
  const pages = scan.result?.pages || [];
  const pagesHtml = pages.map((page, i) => `<div class="run-log-line ${page.status === "ok" ? "ok" : "warn"}"><span>${String(i + 1).padStart(2, "0")}</span><span>${e(page.status === "ok" ? `${page.requested_url || page.final_url} — ${page.violations?.length || 0} rules flagged` : `${page.requested_url || "Page"} — ${page.error || page.status}`)}</span></div>`).join("");
  return `<div class="run-log"><div class="run-log-head"><span>RUN / ${e(scan.id.slice(0, 8).toUpperCase())}</span><span>${statusBadge(scan.status)}</span></div><div class="run-log-line"><span>↳</span><span>axe-core ${e(scan.axe_version || "version unavailable")} · ${e(formatDate(scan.started_at))}</span></div>${pagesHtml || `<div class="run-log-line warn"><span>!</span><span>Scan did not return page results.</span></div>`}</div>`;
}

function renderOverview(audit) {
  const summary = summarizeAudit(audit);
  const pages = audit.pages || [];
  const selectedFindings = (audit.findings || []).filter(item => item.scan_id === summary.latestScan?.id).slice(0, 4);
  return `${renderSampleBanner(audit)}${renderStats(audit)}<div class="overview-grid">
    <section class="panel panel-pad"><div class="panel-heading"><div><h3>Scan scope</h3><p>${pages.length} explicit page${pages.length === 1 ? "" : "s"} · no link crawling</p></div><span class="badge badge-neutral">${e(audit.auditor)}</span></div>
      <div class="page-list">${pages.map((page, index) => `<div class="page-row"><span class="page-index">${String(index + 1).padStart(2, "0")}</span><div><div class="page-title">${e(page.label)}</div><div class="page-url">${e(page.url)}</div></div>${statusBadge(summary.latestScan?.result?.pages?.find(result => result.requested_url === page.url)?.status || "not_checked")}</div>`).join("")}</div>
      <div class="space-before-scope"><span class="eyebrow">SCOPE / ${e(audit.client_name)}</span><p class="muted small space-after-note">${e(audit.scope)}</p></div>
    </section>
    <section class="panel panel-pad"><div class="panel-heading"><div><h3>Latest run</h3><p>Every page returns evidence or an explicit error.</p></div><span class="nav-glyph">⌁</span></div>${renderScanLog(audit)}</section>
  </div>
  <div class="section-row"><h2>Latest findings</h2><button class="button button-quiet" data-tab="findings">OPEN REVIEW QUEUE <span aria-hidden="true">↗</span></button></div>
  <div class="section-row"><h2>Audit timeline</h2><span class="section-meta">LOCAL ACTIVITY</span></div><section class="panel timeline">${(audit.events || []).slice(0, 8).map(item => `<div class="timeline-item"><span class="timeline-dot" aria-hidden="true"></span><strong>${e(item.event_type.replaceAll("_", " "))}</strong><time>${e(formatDate(item.created_at))}</time></div>`).join("") || `<p class="muted small">No activity recorded yet.</p>`}</section>
  ${selectedFindings.length ? `<div class="panel panel-pad">${selectedFindings.map(item => `<button class="page-row finding-preview" data-action="select-finding" data-id="${e(item.id)}"><span class="impact ${impactClass(item.impact)}">${e(item.impact)}</span><div><div class="page-title">${e(item.help)}</div><div class="page-url">${e(item.page_label)} / ${e(item.rule_id)}</div></div>${statusBadge(item.review_status)}</button>`).join("")}</div>` : `<div class="panel panel-pad muted small">No scan yet. Run a scan to create a review queue from actual site evidence.</div>`}`;
}

function currentFindings(audit) {
  const summary = summarizeAudit(audit);
  return (audit.findings || []).filter(item => !summary.latestScan || item.scan_id === summary.latestScan.id);
}

function findingList(findings) {
  const filtered = filterFindings(findings, state.filter);
  if (!filtered.length) return `<div class="empty-state"><span class="empty-glyph">⌕</span><h3>No findings match</h3><p>Clear one of the filters to see more evidence.</p></div>`;
  if (!state.selectedFindingId || !filtered.some(item => item.id === state.selectedFindingId)) state.selectedFindingId = filtered[0].id;
  return filtered.map(item => `<button class="finding-item ${state.selectedFindingId === item.id ? "is-selected" : ""}" data-action="select-finding" data-id="${e(item.id)}">
    <span class="finding-item-top"><span class="impact ${impactClass(item.impact)}">${e(item.impact || "unknown")}</span>${statusBadge(item.review_status)}</span>
    <strong>${e(item.help || item.rule_id)}</strong><small>${e(item.page_label)} / ${e(item.rule_id)}</small>
  </button>`).join("");
}

function renderGemmaPanel(finding) {
  const item = state.explanations[finding.id];
  if (state.explanationBusy) return `<section class="gemma-panel" aria-live="polite"><div class="gemma-heading"><strong>LOCAL GEMMA / THINKING</strong><span class="badge badge-neutral">PRIVATE</span></div><p class="muted small space-after-copy">Gemma is explaining the selected scanner evidence. Your review status will not change.</p></section>`;
  if (!item) return `<section class="gemma-panel"><div class="gemma-heading"><strong>GEMMA / LOCAL EXPLANATION</strong><span class="badge badge-neutral">OPTIONAL</span></div><p class="muted small space-note-copy">Explain this scanner rule and suggest one repair check. The model cannot add findings or mark this one fixed.</p><button class="button button-secondary" data-action="explain-finding" data-id="${e(finding.id)}">ASK ${e(state.settings.model || "GEMMA")} <span aria-hidden="true">✳</span></button></section>`;
  const context = item.context_sent || {};
  const answer = item.explanation;
  return `<section class="gemma-panel"><div class="gemma-heading"><strong>${e(item.model || state.settings.model)} / ${answer ? "EXPLANATION" : "RAW TEXT ONLY"}</strong>${item.response_valid ? `<span class="badge badge-good">STRUCTURED</span>` : `<span class="badge badge-warn">UNPARSED</span>`}</div>
    ${answer ? `<div class="gemma-answer"><div><h4>Why this matters</h4><p>${e(answer.impact_plain_language)}</p></div><div><h4>Suggested repair</h4><p>${e(answer.suggested_repair)}</p></div><div><h4>Check the repair</h4><p>${e(answer.verification_step)}</p></div></div>` : `<p class="muted small space-vertical-small">${e(item.raw_answer || item.error || "No explanation text returned.")}</p>`}
    <details class="context-details"><summary>INSPECT THE EXACT CONTEXT SENT TO GEMMA</summary><pre>${e(JSON.stringify(context, null, 2))}</pre></details>
    <button class="button button-quiet space-before-small" data-action="explain-finding" data-id="${e(finding.id)}">ASK AGAIN</button></section>`;
}

function renderFindingDetail(finding) {
  if (!finding) return `<div class="empty-state"><span class="empty-glyph">⌕</span><h3>Choose a finding</h3><p>Select an item from the review queue to inspect its evidence.</p></div>`;
  const firstNode = finding.nodes?.[0];
  return `<section class="panel panel-pad finding-detail">
    <div class="panel-heading"><div><span class="eyebrow">${e(finding.rule_id)} / ${e(finding.page_label)}</span><h2 class="space-before-title">${e(finding.help || finding.rule_id)}</h2></div><span class="impact ${impactClass(finding.impact)}">${e(finding.impact)}</span></div>
    <p class="finding-description">${e(finding.description)}</p>
    ${firstNode ? `<div class="evidence-box"><div class="evidence-label">Affected target</div><code>${e((firstNode.target || []).join(" · ") || "Selector not provided")}</code></div>
      <div class="evidence-box"><div class="evidence-label">HTML excerpt / displayed as text</div><code>${e(firstNode.html || "No excerpt returned")}</code></div>
      <div class="evidence-box"><div class="evidence-label">Scanner evidence</div><p class="small muted-zero">${e(firstNode.failure_summary || "Review the element and rule description manually.")}</p></div>` : ""}
    ${finding.help_url ? `<p class="page-url">Rule reference: ${e(finding.help_url)}</p>` : ""}
    <div class="detail-form"><label>Review status<select class="form-control" id="finding-status"><option value="needs_review" ${finding.review_status === "needs_review" ? "selected" : ""}>Needs review</option><option value="confirmed" ${finding.review_status === "confirmed" ? "selected" : ""}>Confirmed</option><option value="fixed" ${finding.review_status === "fixed" ? "selected" : ""}>Fixed</option><option value="not_applicable" ${finding.review_status === "not_applicable" ? "selected" : ""}>Not applicable</option></select></label><label>Auditor note<input id="finding-note" class="finding-note" maxlength="4000" value="${e(finding.note || "")}" placeholder="What did you verify?" /></label><button class="button button-secondary" data-action="save-finding" data-id="${e(finding.id)}">SAVE REVIEW</button></div>
    ${renderGemmaPanel(finding)}
  </section>`;
}

function renderFindings(audit) {
  const findings = currentFindings(audit);
  if (findings.length && !findings.some(item => item.id === state.selectedFindingId)) state.selectedFindingId = findings[0].id;
  const selected = findings.find(item => item.id === state.selectedFindingId);
  return `${renderSampleBanner(audit)}<div class="section-row no-top-margin"><div><h2>Review queue</h2><span class="section-meta">${findings.length.toString().padStart(2, "0")} FINDINGS / HUMAN REVIEW REQUIRED</span></div>${statusBadge(summarizeAudit(audit).latestScan?.status || "not_checked")}</div>
  ${findings.length ? `<div class="filter-bar"><input id="finding-search" type="search" aria-label="Search findings" placeholder="Search rule, page, or description…" value="${e(state.filter.query)}"><select id="finding-impact" aria-label="Filter impact"><option value="all">All impact</option>${["critical", "serious", "moderate", "minor"].map(x => `<option value="${x}" ${state.filter.impact === x ? "selected" : ""}>${x[0].toUpperCase() + x.slice(1)}</option>`).join("")}</select><select id="finding-review-status" aria-label="Filter review status"><option value="all">All review states</option>${[["needs_review", "Needs review"], ["confirmed", "Confirmed"], ["fixed", "Fixed"], ["not_applicable", "Not applicable"]].map(([value, label]) => `<option value="${value}" ${state.filter.status === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
  <div class="findings-layout"><div class="finding-list" id="finding-list" aria-label="Accessibility findings">${findingList(findings)}</div><div id="finding-detail">${renderFindingDetail(selected)}</div></div>` : `<div class="empty-state"><span class="empty-glyph">⌁</span><h2>No scan findings yet</h2><p>Run a scan on a client audit to build a queue of specific, reviewable evidence.</p><button class="button button-primary" data-action="start-scan">RUN ACCESSIBILITY SCAN</button></div>`}`;
}

function renderManualChecks(audit) {
  return `${renderSampleBanner(audit)}<div class="section-row no-top-margin"><div><h2>The human pass</h2><span class="section-meta">AUTOMATION DOES NOT COVER THESE CHECKS</span></div><span class="badge badge-neutral">${audit.manual_checks.filter(item => item.status !== "not_checked").length}/${audit.manual_checks.length} CHECKED</span></div>
  <p class="lede space-after">Capture what you checked yourself. These results stay separate from automated scanner findings in the client report.</p>
  <div class="checklist">${audit.manual_checks.map(check => `<div class="check-row" data-check-row="${e(check.id)}"><div><div class="check-title">${e(check.label)}</div><div class="check-description">${e(checkHelp[check.check_key] || "Record what you observed during manual review.")}</div></div>
    <label>Status<select class="form-control check-select" aria-label="${e(check.label)} status"><option value="not_checked" ${check.status === "not_checked" ? "selected" : ""}>Not checked</option><option value="pass" ${check.status === "pass" ? "selected" : ""}>Pass</option><option value="issue" ${check.status === "issue" ? "selected" : ""}>Issue found</option></select></label>
    <label>Auditor note<input class="check-note" maxlength="4000" value="${e(check.note || "")}" placeholder="What did you observe?" /></label>
    <button class="button button-quiet" data-action="save-check" data-id="${e(check.id)}">SAVE</button></div>`).join("")}</div>`;
}

function renderCompare(audit) {
  const scans = audit.scan_runs || [];
  const baselineDefault = scans[1]?.id || "";
  const currentDefault = scans[0]?.id || "";
  return `${renderSampleBanner(audit)}<div class="section-row no-top-margin"><div><h2>Show the movement</h2><span class="section-meta">COMPARE TWO SAVED SCANS</span></div><span class="badge badge-neutral">${scans.length} RUN${scans.length === 1 ? "" : "S"}</span></div>
  ${scans.length < 2 ? `<div class="empty-state"><span class="empty-glyph">⌁</span><h3>Run the next scan to compare progress</h3><p>Previous findings and notes stay preserved. A fresh scan will show resolved, new, and still-open findings.</p><button class="button button-secondary" data-action="start-scan" ${audit.demo ? "disabled" : ""}>RUN ANOTHER SCAN</button></div>` : `<section class="panel panel-pad"><form id="compare-form" class="compare-form"><label>Baseline scan<select class="compare-select" name="baseline">${scans.map(scan => `<option value="${e(scan.id)}" ${scan.id === baselineDefault ? "selected" : ""}>${e(formatDate(scan.started_at))} / ${e(scan.status)}</option>`).join("")}</select></label><label>Current scan<select class="compare-select" name="current">${scans.map(scan => `<option value="${e(scan.id)}" ${scan.id === currentDefault ? "selected" : ""}>${e(formatDate(scan.started_at))} / ${e(scan.status)}</option>`).join("")}</select></label><button class="button button-primary" type="submit">COMPARE RUNS</button></form>
    ${state.compare ? `<div class="compare-result"><span class="eyebrow">${e(formatDate(state.compare.baseline.started_at))} → ${e(formatDate(state.compare.current.started_at))}</span><div class="delta-grid"><div class="delta-card"><span>Baseline findings</span><strong>${state.compare.baseline.total}</strong></div><div class="delta-card"><span>Current findings</span><strong>${state.compare.current.total}</strong></div><div class="delta-card"><span>Resolved evidence</span><strong class="impact-moderate">${state.compare.resolved}</strong></div><div class="delta-card"><span>New evidence</span><strong class="${state.compare.new ? "impact-serious" : "impact-minor"}">${state.compare.new}</strong></div></div><div class="page-list space-before-medium">${Object.entries(state.compare.by_impact || {}).map(([impact, counts]) => `<div class="page-row"><span class="impact ${impactClass(impact)}">${e(impact)}</span><span class="muted small">${counts.before} before</span><strong class="mono">${counts.after} now</strong></div>`).join("")}</div><p class="muted small space-after-copy">A comparison matches rule, page, and target evidence. Human review statuses remain visible on each saved finding.</p></div>` : `<div class="empty-state empty-state-short"><span class="empty-glyph">Δ</span><p>Select two different scans to compare.</p></div>`}
  </section>`}`;
}

function renderReport(audit) {
  const report = state.report;
  if (!report) return `${renderSampleBanner(audit)}<div class="report-toolbar"><div><span class="eyebrow">DELIVERABLE / HUMAN-REVIEWED</span><h2 class="space-before-title">A report your client can act on.</h2><p class="muted small">Preview includes scan coverage, reviewed findings, and hands-on checks.</p></div><div><button class="button button-primary" data-action="load-report">BUILD CLIENT REPORT</button></div></div>
  <section class="panel report-placeholder"><div class="empty-state borderless empty-state-short"><span class="empty-glyph">▤</span><h3>Ready when you are</h3><p>Build a fresh report from the saved audit evidence.</p></div></section>`;
  return `<div class="report-toolbar"><div><span class="eyebrow">DELIVERABLE / HUMAN-REVIEWED</span><h2 class="space-before-title">${e(report.title)}</h2><p class="muted small">Prepared ${e(formatDate(report.generated_at))} · ${e(report.client_name)}</p></div><div class="report-actions"><button class="button button-secondary" data-action="export-backup">EXPORT JSON BACKUP</button><button class="button button-primary" data-action="print-report">SAVE AS PDF / PRINT</button></div></div>
  <article class="report-sheet"><header><span class="eyebrow">ACCESSIBILITY REVIEW / ${e(report.audit_name)}</span><h1>${e(report.client_name)}</h1><p>${e(report.scope)}</p><p class="small">Prepared by ${e(report.auditor)} · ${e(report.generated_at.slice(0, 10))}</p></header>
  <div class="report-metrics"><div><strong>${report.coverage.scanned}/${report.coverage.total}</strong><span>Pages scanned</span></div><div><strong>${report.summary.findings}</strong><span>Automated findings</span></div><div><strong>${report.summary.unresolved_high_priority}</strong><span>Unresolved critical / serious</span></div><div><strong>${report.summary.manual_completed}/${report.summary.manual_total}</strong><span>Manual checks recorded</span></div></div>
  ${report.coverage.pages.length ? `<section><h2>Page coverage</h2>${report.coverage.pages.map(page => `<div class="report-row"><strong>${e(page.label)}</strong><span>${e(page.status)}</span><small>${e(page.url)}</small></div>`).join("")}</section>` : `<section><h2>Page coverage</h2><p>No scan has been run yet.</p></section>`}
  ${report.findings.length ? `<section><h2>Findings for human review</h2>${report.findings.map(item => `<div class="report-finding"><div class="report-row"><strong>${e(item.help)}</strong><span class="impact ${impactClass(item.impact)}">${e(item.impact)}</span></div><p>${e(item.page_label)} · ${e(item.rule_id)} · ${e(item.review_status.replaceAll("_", " "))}</p><p>${e(item.description)}</p>${item.note ? `<p><strong>Auditor note:</strong> ${e(item.note)}</p>` : ""}</div>`).join("")}</section>` : `<section><h2>Findings</h2><p>No automated findings are recorded.</p></section>`}
  <section><h2>Hands-on checks</h2>${report.manual_checks.map(check => `<div class="report-row"><strong>${e(check.label)}</strong><span>${e(check.status.replaceAll("_", " "))}</span>${check.note ? `<small>${e(check.note)}</small>` : ""}</div>`).join("")}</section>
  <footer>${e(report.disclaimer)}<p class="small">Tools: ${e(report.tools.axe_core)} / ${e(report.tools.browser)} · Model assistance: ${e(report.tools.model)}</p></footer></article>`;
}

function renderAudit() {
  const audit = state.audit;
  if (!audit) return renderDashboard();
  state.screen = "audit";
  setCrumb(`${audit.demo ? "Sample" : "Client audit"} / ${audit.name}`);
  const panel = {
    overview: renderOverview, findings: renderFindings, manual: renderManualChecks,
    compare: renderCompare, report: renderReport,
  }[state.tab] || renderOverview;
  app.innerHTML = `${auditHeader(audit, summarizeAudit(audit))}<section id="audit-panel">${panel(audit)}</section>`;
}

function renderSettings() {
  state.screen = "settings";
  setCrumb("Local model setup");
  const status = state.health?.ollama;
  const message = status?.available ? status.message : (status?.message || "Checking local Ollama status…");
  app.innerHTML = `<div class="page-head"><div><span class="eyebrow">PRIVATE INFERENCE / LOOPBACK ONLY</span><h1>Model <em>setup.</em></h1><p class="lede">AccessSprint sends the selected finding’s rule and bounded evidence to Ollama on this computer. Client names and audit notes stay out of the prompt.</p></div></div>
  <div class="settings-grid"><section class="panel panel-pad"><div class="panel-heading"><div><h3>Ollama connection</h3><p>Both address and model tag are saved in your local audit database.</p></div>${statusBadge(status?.model_installed ? "pass" : status?.available ? "issue" : "not_checked")}</div>
    <form id="settings-form" class="settings-form"><label>Local Ollama address<input name="base_url" type="url" required value="${e(state.settings.base_url)}" placeholder="http://127.0.0.1:11434"><span class="small dim">Loopback addresses only. AccessSprint rejects remote model URLs.</span></label>
      <label>Model tag<input name="model" required maxlength="120" value="${e(state.settings.model)}" placeholder="gemma4:e4b"><span class="small dim">Default: <code class="mono">gemma4:e4b</code></span></label>
      <div class="settings-actions"><button class="button button-primary" type="submit">SAVE LOCAL SETTINGS</button><button class="button button-secondary" type="button" data-action="test-model">TEST LOCAL MODEL</button></div>
    </form><p class="form-error" id="settings-error" role="alert"></p></section>
    <aside class="settings-note"><strong>MODEL STATUS / ${status?.model_installed ? "READY" : status?.available ? "TAG NOT FOUND" : "OFFLINE"}</strong><p class="space-vertical-note">${e(message)}</p>${!status?.model_installed ? `<p>In PowerShell, pull your local model with:</p><p><code>ollama pull ${e(state.settings.model || "gemma4:e4b")}</code></p>` : `<p>Only the selected finding context is sent for an explanation. The model cannot create or close audit findings.</p>`}<hr class="settings-rule"><strong>DATA PATH</strong><p class="space-after-note">Audit records live in the AccessSprint folder under your local application data. Use JSON backups before changing computers.</p></aside>
  </div>`;
}

function render() {
  if (state.screen === "dashboard") return renderDashboard();
  if (state.screen === "settings") return renderSettings();
  if (state.screen === "audit") return renderAudit();
}

async function openAudit(id) {
  try {
    state.audit = await api.getAudit(id);
    state.tab = "overview";
    state.selectedFindingId = state.audit.findings?.[0]?.id || null;
    state.filter = { impact: "all", status: "all", query: "" };
    state.compare = null;
    renderAudit();
  } catch (error) { renderError("Could not open this audit", error.message); }
}

async function reloadAudit() {
  if (!state.audit) return;
  state.audit = await api.getAudit(state.audit.id);
  state.details.set(state.audit.id, state.audit);
  if (state.screen === "audit") renderAudit();
}

function showNewAudit() {
  state.editingAuditId = null;
  document.querySelector("#dialog-eyebrow").textContent = "NEW CLIENT RUN / 01";
  document.querySelector("#dialog-title").textContent = "Set the scope.";
  document.querySelector("#audit-submit").innerHTML = 'CREATE AUDIT <span aria-hidden="true">↗</span>';
  document.querySelector("#audit-form").reset();
  document.querySelector("#audit-form-error").textContent = "";
  dialog.showModal();
  dialog.querySelector("input[name=name]").focus();
}

function showEditAudit() {
  const audit = state.audit;
  if (!audit || audit.demo) return;
  state.editingAuditId = audit.id;
  const form = document.querySelector("#audit-form");
  for (const key of ["name", "client_name", "auditor", "base_url", "scope"]) form.elements[key].value = audit[key];
  form.elements.pages.value = audit.pages.map(page => page.url).join("\n");
  document.querySelector("#dialog-eyebrow").textContent = "EDIT CLIENT RUN / SCOPE";
  document.querySelector("#dialog-title").textContent = "Update the scope.";
  document.querySelector("#audit-submit").innerHTML = 'SAVE CHANGES <span aria-hidden="true">↗</span>';
  document.querySelector("#audit-form-error").textContent = "";
  dialog.showModal();
  form.elements.name.focus();
}

function closeDialog() { if (dialog.open) dialog.close(); state.editingAuditId = null; }

async function submitAudit(event) {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  const lines = String(data.get("pages") || "").split(/\r?\n/).map(line => line.trim()).filter(Boolean);
  const pages = lines.map((url, index) => {
    let label = `Page ${index + 1}`;
    try {
      const parsed = new URL(url);
      label = parsed.pathname === "/" ? "Homepage" : decodeURIComponent(parsed.pathname.split("/").filter(Boolean).pop() || `Page ${index + 1}`).replace(/[-_]/g, " ");
    } catch { /* backend returns the precise URL validation message */ }
    return { url, label };
  });
  const payload = {
    name: data.get("name"), client_name: data.get("client_name"), auditor: data.get("auditor"),
    base_url: data.get("base_url"), scope: data.get("scope"), pages,
  };
  const submit = form.querySelector("button[type=submit]");
  submit.setAttribute("aria-busy", "true");
  document.querySelector("#audit-form-error").textContent = "";
  try {
    const audit = state.editingAuditId
      ? await api.updateAudit(state.editingAuditId, payload)
      : await api.createAudit(payload);
    closeDialog();
    form.reset();
    if (state.screen === "audit" && state.audit?.id === audit.id) {
      state.audit = audit;
      state.details.set(audit.id, audit);
      await refreshDashboard();
      renderAudit();
      toastMessage("Audit details and page scope updated.");
    } else {
      await refreshDashboard();
      toastMessage("Audit created. Review the scope, then start your first scan.");
      await openAudit(audit.id);
    }
  } catch (error) {
    document.querySelector("#audit-form-error").textContent = error.message;
  } finally { submit.removeAttribute("aria-busy"); }
}

async function startScan() {
  if (!state.audit || state.audit.demo || state.scanBusy) return;
  state.scanBusy = true;
  renderAudit();
  try {
    const scan = await api.startScan(state.audit.id);
    state.audit.scan_runs.unshift(scan);
    state.audit.scan_runs = state.audit.scan_runs.slice(0, 30);
    toastMessage("Scan started. Each page will show findings or an explicit error.");
    beginPolling(scan.id);
  } catch (error) {
    state.scanBusy = false;
    renderAudit();
    toastMessage(error.message, true);
  }
}

function beginPolling(scanId) {
  clearInterval(scanTimer);
  scanTimer = setInterval(async () => {
    try {
      const scan = await api.getScan(scanId);
      if (state.audit) {
        const index = state.audit.scan_runs.findIndex(item => item.id === scan.id);
        if (index >= 0) state.audit.scan_runs[index] = scan;
        else state.audit.scan_runs.unshift(scan);
        state.audit.findings = [...(state.audit.findings || []).filter(item => item.scan_id !== scan.id), ...(scan.findings || [])];
      }
      if (scan.status !== "running") {
        clearInterval(scanTimer);
        state.scanBusy = false;
        state.selectedFindingId = scan.findings?.[0]?.id || null;
        await reloadAudit();
        toastMessage(scan.status === "completed" ? "Scan complete. Your findings are ready for human review." : `Scan ${scan.status}. Check the per-page result log.` , scan.status === "failed");
      } else renderAudit();
    } catch (error) {
      clearInterval(scanTimer);
      state.scanBusy = false;
      toastMessage(error.message, true);
    }
  }, 1100);
}

async function saveFinding(button) {
  const id = button.dataset.id;
  try {
    await api.reviewFinding(state.audit.id, id, {
      status: document.querySelector("#finding-status").value,
      note: document.querySelector("#finding-note").value,
    });
    await reloadAudit();
    toastMessage("Review state saved locally.");
  } catch (error) { toastMessage(error.message, true); }
}

async function explainFinding(id) {
  state.explanationBusy = true;
  renderAudit();
  try {
    state.explanations[id] = await api.explainFinding(state.audit.id, id);
  } catch (error) {
    state.explanations[id] = { error: error.message, context_sent: {}, response_valid: false, raw_answer: null };
  } finally {
    state.explanationBusy = false;
    renderAudit();
  }
}

async function saveManualCheck(button) {
  const row = button.closest("[data-check-row]");
  try {
    await api.updateManualCheck(state.audit.id, button.dataset.id, {
      status: row.querySelector("select").value,
      note: row.querySelector("input").value,
    });
    await reloadAudit();
    toastMessage("Manual check saved.");
  } catch (error) { toastMessage(error.message, true); }
}

async function runComparison(form) {
  const data = new FormData(form);
  if (data.get("baseline") === data.get("current")) {
    toastMessage("Choose two different scan runs.", true);
    return;
  }
  try {
    state.compare = await api.compareScans(state.audit.id, data.get("baseline"), data.get("current"));
    renderAudit();
  } catch (error) { toastMessage(error.message, true); }
}

async function saveSettings(form) {
  const submit = form.querySelector("button[type=submit]");
  submit.setAttribute("aria-busy", "true");
  document.querySelector("#settings-error").textContent = "";
  try {
    state.settings = (await api.saveSettings({
      base_url: form.elements.base_url.value.trim(), model: form.elements.model.value.trim(),
    })).settings;
    await refreshHealth();
    renderSettings();
    toastMessage("Local model settings saved.");
  } catch (error) {
    document.querySelector("#settings-error").textContent = error.message;
  } finally { submit.removeAttribute("aria-busy"); }
}

async function testModel() {
  const button = document.querySelector('[data-action="test-model"]');
  button?.setAttribute("aria-busy", "true");
  try {
    const result = await api.testModel();
    toastMessage(result.test.message);
    await refreshHealth();
  } catch (error) {
    toastMessage(error.message, true);
    await refreshHealth();
  } finally { button?.removeAttribute("aria-busy"); renderSettings(); }
}

async function refreshHealth() {
  state.health = await api.health();
}

async function loadReport() {
  try {
    state.report = await api.report(state.audit.id);
    renderAudit();
  } catch (error) { toastMessage(error.message, true); }
}

async function exportBackup() {
  try {
    const backup = await api.exportBackup(state.audit.id);
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `accesssprint-${state.audit.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "audit"}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    toastMessage("Encrypted-by-location JSON backup downloaded.");
  } catch (error) { toastMessage(error.message, true); }
}

async function importBackupFile(file) {
  try {
    if (file.size > 1_000_000) throw new Error("Backup file is larger than the 1 MB import limit.");
    const parsed = JSON.parse(await file.text());
    const imported = await api.importBackup(parsed);
    await refreshDashboard();
    await openAudit(imported.id);
    toastMessage("Backup restored as a new audit.");
  } catch (error) { toastMessage(error.message || "That file is not a valid AccessSprint backup.", true); }
}

function refreshFindingList() {
  if (!state.audit) return;
  state.filter.query = document.querySelector("#finding-search")?.value || "";
  state.filter.impact = document.querySelector("#finding-impact")?.value || "all";
  state.filter.status = document.querySelector("#finding-review-status")?.value || "all";
  const list = document.querySelector("#finding-list");
  if (list) list.innerHTML = findingList(currentFindings(state.audit));
}

document.addEventListener("click", async event => {
  const tab = event.target.closest("[data-tab]");
  if (tab) {
    state.tab = tab.dataset.tab;
    state.compare = null;
    if (state.tab === "report") state.report = null;
    renderAudit();
    return;
  }
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const { action } = button.dataset;
  if (action === "dashboard") {
    clearInterval(scanTimer);
    state.audit = null;
    state.screen = "dashboard";
    renderDashboard();
    refreshDashboard().then(renderDashboard).catch(error => renderError("Audit desk unavailable", error.message));
  } else if (action === "settings") {
    state.screen = "settings";
    if (!state.settingsLoaded) {
      try { state.settings = (await api.settings()).settings; state.settingsLoaded = true; }
      catch (error) { toastMessage(error.message, true); }
    }
    renderSettings();
  } else if (action === "new-audit") showNewAudit();
  else if (action === "edit-audit") showEditAudit();
  else if (action === "import-backup-file") document.querySelector("#backup-file")?.click();
  else if (action === "restore-audit") {
    try { await api.archiveAudit(button.dataset.id, false); await refreshDashboard(); renderDashboard(); toastMessage("Audit restored to your active workspace."); }
    catch (error) { toastMessage(error.message, true); }
  }
  else if (action === "delete-audit") {
    if (state.audit && window.confirm(`Permanently delete “${state.audit.name}” and its local scans? This cannot be undone.`)) {
      try { await api.deleteAudit(state.audit.id); state.audit = null; await refreshDashboard(); renderDashboard(); toastMessage("Audit and its saved findings were deleted."); }
      catch (error) { toastMessage(error.message, true); }
    }
  }
  else if (action === "close-dialog") closeDialog();
  else if (action === "open-audit") await openAudit(button.dataset.id);
  else if (action === "start-scan") await startScan();
  else if (action === "select-finding") {
    state.selectedFindingId = button.dataset.id;
    renderAudit();
  } else if (action === "save-finding") await saveFinding(button);
  else if (action === "explain-finding") await explainFinding(button.dataset.id);
  else if (action === "save-check") await saveManualCheck(button);
  else if (action === "test-model") await testModel();
  else if (action === "load-report") await loadReport();
  else if (action === "export-backup") await exportBackup();
  else if (action === "print-report") window.print();
  else if (action === "archive-audit") {
    try {
      await api.archiveAudit(state.audit.id, true);
      state.audit = null;
      await refreshDashboard(); renderDashboard();
      toastMessage("Audit archived. You can restore it from the audit list.");
    } catch (error) { toastMessage(error.message, true); }
  }
});

document.addEventListener("input", event => {
  if (event.target.matches("#finding-search")) refreshFindingList();
});

document.addEventListener("change", event => {
  if (event.target.matches("#finding-impact, #finding-review-status")) refreshFindingList();
  if (event.target.matches("#backup-file") && event.target.files?.[0]) {
    const [file] = event.target.files;
    event.target.value = "";
    importBackupFile(file);
  }
});

document.addEventListener("submit", async event => {
  if (event.target.id === "audit-form") await submitAudit(event);
  else if (event.target.id === "settings-form") {
    event.preventDefault();
    await saveSettings(event.target);
  } else if (event.target.id === "compare-form") {
    event.preventDefault();
    await runComparison(event.target);
  }
});

async function boot() {
  try {
    const [health, settings] = await Promise.all([api.health(), api.settings()]);
    state.health = health;
    state.settings = settings.settings;
    state.settingsLoaded = true;
    await refreshDashboard();
    renderDashboard();
  } catch (error) {
    setCrumb("Local connection");
    renderError("Start the local workspace", error.message || "Keep the AccessSprint launcher open and reload this page.");
  }
}

boot();

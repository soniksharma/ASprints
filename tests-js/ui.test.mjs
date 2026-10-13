import test from "node:test";
import assert from "node:assert/strict";
import { ApiError, request } from "../web/api.js";
import { escapeHtml, filterFindings, summarizeAudit } from "../web/view-model.js";

const findings = [
  { id: "a", rule_id: "image-alt", impact: "critical", review_status: "needs_review", page_label: "Home" },
  { id: "b", rule_id: "color-contrast", impact: "serious", review_status: "confirmed", page_label: "Menu" },
  { id: "c", rule_id: "link-name", impact: "moderate", review_status: "fixed", page_label: "Home" },
];

test("filters findings by impact, review status, and search term", () => {
  const result = filterFindings(findings, { impact: "serious", status: "confirmed", query: "menu" });
  assert.deepEqual(result.map(item => item.id), ["b"]);
  assert.deepEqual(filterFindings(findings, { impact: "all", status: "all", query: "home" }).map(x => x.id), ["a", "c"]);
});

test("summarizes latest scan and manual review progress", () => {
  const summary = summarizeAudit({
    scan_runs: [{ id: "new", status: "completed" }, { id: "old", status: "completed" }],
    findings: [
      { scan_id: "new", impact: "critical", review_status: "needs_review" },
      { scan_id: "new", impact: "serious", review_status: "fixed" },
      { scan_id: "old", impact: "critical", review_status: "confirmed" },
    ],
    manual_checks: [{ status: "pass" }, { status: "issue" }, { status: "not_checked" }],
  });
  assert.equal(summary.totalFindings, 2);
  assert.equal(summary.highPriority, 1);
  assert.equal(summary.reviewed, 1);
  assert.equal(summary.manualCompleted, 2);
  assert.equal(summary.manualTotal, 3);
  assert.equal(summary.latestScan.status, "completed");
});

test("escapes website evidence before it enters HTML templates", () => {
  assert.equal(escapeHtml(`<img src=x onerror="bad()"> & 'test'`),
    "&lt;img src=x onerror=&quot;bad()&quot;&gt; &amp; &#39;test&#39;");
});

test("API request sends JSON and returns parsed data", async () => {
  let captured;
  const result = await request("/api/audits", { method: "POST", body: { name: "Test" } }, async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ audit: { id: "a" } }), { status: 201,
      headers: { "Content-Type": "application/json" } });
  });
  assert.equal(captured.url, "/api/audits");
  assert.equal(captured.options.method, "POST");
  assert.equal(captured.options.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(captured.options.body), { name: "Test" });
  assert.deepEqual(result, { audit: { id: "a" } });
});

test("API request surfaces server errors as actionable messages", async () => {
  await assert.rejects(request("/api/audits", {}, async () => new Response(
    JSON.stringify({ error: "Enter between 1 and 10 pages." }),
    { status: 400, headers: { "Content-Type": "application/json" } })),
  error => error instanceof ApiError && error.status === 400 && error.message.includes("1 and 10 pages"));
});


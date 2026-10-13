import test from "node:test";
import assert from "node:assert/strict";
import { normalizeAxeResults } from "../scanner/normalize.mjs";

test("normalizes axe evidence into bounded plain data", () => {
  const axe = {
    violations: [{
      id: "color-contrast", impact: "serious", help: "Fix contrast", description: "Text needs contrast.",
      helpUrl: "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
      nodes: [{ target: ["main p"], html: "<p onclick='evil()'>Tiny text</p>", failureSummary: "Fix the foreground/background contrast." }],
    }],
    passes: [{ id: "html-has-lang" }], incomplete: [{ id: "color-contrast" }],
  };
  const result = normalizeAxeResults(axe, "https://example.com/");
  assert.equal(result.violations[0].rule_id, "color-contrast");
  assert.equal(result.violations[0].nodes[0].target[0], "main p");
  assert.equal(result.violations[0].nodes[0].html, "<p onclick='evil()'>Tiny text</p>");
  assert.equal(result.passes, 1);
  assert.equal(result.incomplete, 1);
  assert.equal(result.page_url, "https://example.com/");
});

test("limits hostile or unusually large scanner evidence", () => {
  const huge = "x".repeat(5000);
  const result = normalizeAxeResults({
    violations: [{ id: huge, impact: "critical", help: huge, description: huge, helpUrl: huge,
      nodes: Array.from({ length: 60 }, () => ({ target: [huge], html: huge, failureSummary: huge })) }],
  }, "https://example.com/");
  assert.ok(result.violations[0].rule_id.length <= 100);
  assert.ok(result.violations[0].help.length <= 300);
  assert.equal(result.violations[0].nodes.length, 25);
  assert.ok(result.violations[0].nodes[0].html.length <= 400);
});


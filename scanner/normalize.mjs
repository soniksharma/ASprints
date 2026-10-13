const clip = (value, max) => String(value ?? "").slice(0, max);

export function normalizeAxeResults(results = {}, pageUrl = "") {
  const violations = Array.isArray(results.violations) ? results.violations : [];
  return {
    page_url: clip(pageUrl, 2048),
    violations: violations.slice(0, 300).map(rule => ({
      rule_id: clip(rule.id, 100),
      impact: ["critical", "serious", "moderate", "minor"].includes(rule.impact) ? rule.impact : "unknown",
      help: clip(rule.help, 300),
      description: clip(rule.description, 1200),
      help_url: clip(rule.helpUrl, 500),
      nodes: (Array.isArray(rule.nodes) ? rule.nodes : []).slice(0, 25).map(node => ({
        target: (Array.isArray(node.target) ? node.target : []).slice(0, 5).map(item => clip(item, 300)),
        html: clip(node.html, 400),
        failure_summary: clip(node.failureSummary, 1600),
      })),
    })),
    passes: Array.isArray(results.passes) ? results.passes.length : 0,
    incomplete: Array.isArray(results.incomplete) ? results.incomplete.length : 0,
  };
}

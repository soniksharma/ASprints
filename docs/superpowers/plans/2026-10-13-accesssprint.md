# AccessSprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local-first accessibility audit workspace that helps a freelancer scan, review, explain, and report on small business websites with local Gemma assistance.

**Architecture:** A Python loopback HTTP server owns the API, SQLite database, and Ollama bridge. A small Node worker owns Playwright/Chromium and axe-core scanning; it applies URL checks to navigations, redirects, and subrequests and returns normalized evidence. A static browser UI consumes the API, while a separate print view produces the client report.

**Tech Stack:** Python 3 standard library (`http.server`, `sqlite3`, `unittest`), Node.js 24, pinned `playwright` and `axe-core` packages, plain HTML/CSS/JavaScript, Ollama local chat API with `gemma4:e4b`.

**Spec:** `docs/product-spec.md`

## Global Constraints

- Bind the app to `127.0.0.1` only.
- The default Ollama model tag is exactly `gemma4:e4b`; the Ollama URL must be loopback-only.
- Scan one to ten explicitly entered HTTP/HTTPS pages per run; do not crawl links.
- Reject localhost, private, link-local, and reserved IP destinations for navigations, redirects, and browser subrequests.
- Keep the axe result as the evidence source; Gemma explains evidence and cannot change findings or review status.
- Keep audit storage local; do not send audit data to hosted AI.
- Reports must state scope, incomplete checks, manual-check coverage, and that the audit is not a certification.
- Support keyboard use, visible focus, readable contrast, labels, responsive layout, and reduced motion.
- Add and run tests before production code; use mocked browser/Ollama boundaries for deterministic backend tests and live checks for installed local services.

## Review Focus

- Malformed, credential-bearing, non-HTTP, private-address, and redirecting URLs must be rejected before navigation. Test every rejected URL class in the URL policy task.
- A page can redirect or request private-network resources after a safe first URL. Test redirect and subrequest policy in the scanner task.
- Scanner output can contain hostile HTML, selectors, or prompt-injection text. Test normalization and ensure the UI renders evidence as text and Gemma receives bounded, clearly delimited evidence.
- Ollama can be offline, lack the requested tag, time out, or return malformed output. Test each state while confirming audits and findings remain usable.
- Import files and client report fields can be malformed or contain HTML. Test strict JSON validation and escaped report rendering.

---

### Task 1: Project scaffold and URL policy

**Files:**
- Create: `main.py`
- Create: `accesssprint/__init__.py`
- Create: `accesssprint/config.py`
- Create: `accesssprint/url_policy.py`
- Create: `tests/test_url_policy.py`
- Create: `.gitignore`
- Create: `package.json`

**Interfaces:**
- `url_policy.normalize_page_url(value: str) -> str` returns a canonical HTTP/HTTPS URL or raises `UrlPolicyError`.
- `url_policy.is_public_address(address: str) -> bool` returns false for loopback, private, link-local, multicast, reserved, and unspecified IPs.
- `config.DEFAULT_MODEL == "gemma4:e4b"`; `config.DEFAULT_HOST == "127.0.0.1"`.

- [ ] **Step 1: Write failing URL policy tests** for valid HTTP/HTTPS URLs, whitespace trimming, unsupported schemes, malformed host, URL credentials, localhost names, private IPv4, private IPv6, and public IPv4/IPv6.
- [ ] **Step 2: Run `python -m unittest tests.test_url_policy -v`** and verify it fails because `accesssprint.url_policy` is missing.
- [ ] **Step 3: Implement the URL normalization and IP classification interfaces** in `accesssprint/url_policy.py`; do not perform network requests in this module.
- [ ] **Step 4: Run `python -m unittest tests.test_url_policy -v`** and verify all URL policy cases pass.
- [ ] **Step 5: Add minimal app/package scaffolding and verify** `python main.py --help` and `npm test` are wired without network access.
- [ ] **Step 6: Commit** as `feat: scaffold AccessSprint and URL policy`.

### Task 2: Local audit storage and domain operations

**Files:**
- Create: `accesssprint/store.py`
- Create: `accesssprint/audits.py`
- Create: `tests/test_store.py`
- Create: `tests/test_audits.py`

**Interfaces:**
- `Store(path: Path)` initializes SQLite tables for audits, pages, scan_runs, findings, manual_checks, and audit_events.
- `AuditService(store: Store)` exposes `create_audit(payload)`, `get_audit(audit_id)`, `list_audits()`, `update_audit(audit_id, payload)`, `archive_audit(audit_id, archived)`, `delete_audit(audit_id)`, `compare_scans(audit_id, baseline_id, current_id)`, `set_finding_review(audit_id, finding_id, status, note)`, and `set_manual_check(audit_id, check_id, status, note)`.
- Review statuses are `needs_review`, `confirmed`, `fixed`, and `not_applicable`; manual statuses are `not_checked`, `pass`, and `issue`.

- [ ] **Step 1: Write failing SQLite tests** for audit create/read/update/archive/delete, required fields, page cap, finding status changes, manual-check status changes, event timestamps, scan comparison, and persistence after reopening the database.
- [ ] **Step 2: Run `python -m unittest tests.test_store tests.test_audits -v`** and verify the expected missing-module failures.
- [ ] **Step 3: Implement the schema and service methods** with parameterized SQL, transactions for related writes, and generated IDs.
- [ ] **Step 4: Run those tests** and verify all pass, including persistence through a temporary database file.
- [ ] **Step 5: Commit** as `feat: add local audit storage`.

### Task 3: Browser scan worker

**Files:**
- Create: `scanner/worker.mjs`
- Create: `scanner/policy.mjs`
- Create: `scanner/normalize.mjs`
- Create: `tests-js/policy.test.mjs`
- Create: `tests-js/normalize.test.mjs`
- Create: `tests-js/scanner.integration.test.mjs`
- Modify: `package.json`
- Create: `package-lock.json`

**Interfaces:**
- `assertPublicRequestUrl(url: string) -> Promise<URL>` rejects unsafe URL classes using DNS lookups and `isPublicAddress`-equivalent IPv4/IPv6 classification.
- `normalizeAxeResults(results, pageUrl) -> { violations, passes, incomplete }` emits bounded plain-data records; evidence fields are length-limited.
- Worker invocation: `node scanner/worker.mjs <input-json-path> <output-json-path>`; input contains `runId` and normalized page URLs, output contains one explicit success/error result per page.

- [ ] **Step 1: Write failing Node tests** for public and unsafe request URLs, private DNS answers, redirects, browser subrequests, axe result normalization, escaped/untrusted evidence, and per-page timeout results.
- [ ] **Step 2: Run `npm test`** and verify failures are due to missing scanner modules.
- [ ] **Step 3: Add pinned `playwright` and `axe-core` dependencies and implement the policy and normalizer**; apply route checks to every browser request, reject unsafe redirect destinations, use a fresh browser context, and set bounded navigation/action timeouts.
- [ ] **Step 4: Implement worker execution** to navigate each supplied page, inject the local axe-core script, record rule and node evidence, and report failures without turning them into clean scans.
- [ ] **Step 5: Run `npm test`** and verify unit tests pass; install Chromium and run `node --test tests-js/scanner.integration.test.mjs` against a local fixture page with known violations and a clean page.
- [ ] **Step 6: Commit** as `feat: scan explicit pages with local axe-core`.

### Task 4: HTTP API, scan lifecycle, and local Gemma bridge

**Files:**
- Create: `accesssprint/server.py`
- Create: `accesssprint/scans.py`
- Create: `accesssprint/ollama.py`
- Create: `tests/test_api.py`
- Create: `tests/test_scans.py`
- Create: `tests/test_ollama.py`
- Modify: `main.py`

**Interfaces:**
- `create_server(host=config.DEFAULT_HOST, port=8000, data_dir=...)` returns a loopback-only `ThreadingHTTPServer`.
- JSON API: `GET /api/health`, `GET/POST /api/audits`, `GET/PATCH/DELETE /api/audits/{id}`, `POST /api/audits/{id}/archive`, `POST /api/audits/{id}/scans`, `GET /api/scans/{id}`, `GET /api/audits/{id}/scans/compare?baseline={id}&current={id}`, `PATCH /api/audits/{id}/findings/{finding_id}`, `PATCH /api/audits/{id}/manual-checks/{check_id}`, `GET/POST /api/settings`, `POST /api/ai/test`, and `POST /api/ai/explain`.
- `OllamaClient(base_url, model, opener=...)` exposes `status()`, `test_connection()`, and `explain_finding(finding)`. The client only accepts loopback base URLs and a bounded structured response; its default model is `gemma4:e4b`.
- `ScanService` persists a running scan, invokes the worker without a shell, stores per-page outcomes, normalizes findings, and records a completed/partial/failed state.

- [ ] **Step 1: Write failing API and service tests** for route methods including archive, compare, settings and model test, malformed JSON, oversized bodies, unknown audit IDs, invalid statuses, safe subprocess argument passing, scan persistence, offline Ollama, missing model, timeout, malformed model output, and fixed-size request context.
- [ ] **Step 2: Run `python -m unittest tests.test_api tests.test_scans tests.test_ollama -v`** and verify the expected missing-module failures.
- [ ] **Step 3: Implement API validation and storage wiring** with JSON-only responses, request size limits, safe static-file path resolution, no shell invocation, and useful 4xx/5xx errors.
- [ ] **Step 4: Implement scan lifecycle and Ollama client**; do not let AI responses mutate findings, review state, scan status, or severity.
- [ ] **Step 5: Run backend tests** and verify all service states pass without requiring Ollama or Chromium.
- [ ] **Step 6: Commit** as `feat: add audit and local Gemma APIs`.

### Task 5: Interactive AccessSprint workspace

**Files:**
- Create: `web/index.html`
- Create: `web/styles.css`
- Create: `web/app.js`
- Create: `web/api.js`
- Create: `tests-js/ui.test.mjs`
- Modify: `accesssprint/server.py`

**Interfaces:**
- Frontend API client exports `request(path, options)`, `loadAudits()`, `createAudit(payload)`, `startScan(auditId)`, `loadAudit(auditId)`, and `explainFinding(findingId)`.
- Screens: welcome/demo, audit workspace, findings review, manual checks, compare scans, settings, and report preview.
- Hackerish visual treatment uses near-black surfaces, green status indicators, compact monospace metadata, restrained scan animation, and high-contrast prose. Client reports use a separate calm print layout.

- [ ] **Step 1: Write failing UI logic tests** for API error presentation, scan progress states, finding filters/status updates, safe text rendering of evidence, and report-summary counts.
- [ ] **Step 2: Run `npm test`** and verify failures identify missing UI modules.
- [ ] **Step 3: Implement the API client and interactive workspace** with semantic landmarks, labels, keyboard-operable controls, visible focus, reduced-motion behavior, responsive layout, loading/empty/error states, and a demo audit entry point.
- [ ] **Step 4: Implement findings review, manual checklist, scan comparison, and model context inspection**; make all evidence text-only and show when Gemma is unavailable.
- [ ] **Step 5: Run `npm test` and the browser interaction suite** for first-run setup, audit creation, scan progress/error handling, review updates, manual checks, and offline AI messaging.
- [ ] **Step 6: Commit** as `feat: build interactive audit workspace`.

### Task 6: Client report and portable backups

**Files:**
- Create: `accesssprint/reports.py`
- Create: `web/report.js`
- Create: `tests/test_reports.py`
- Create: `tests-js/report.test.mjs`
- Modify: `accesssprint/server.py`
- Modify: `web/styles.css`

**Interfaces:**
- `build_report(audit: dict) -> dict` builds the versioned report payload with scope, page coverage, severity counts, reviewed findings, manual checks, limitations, and tool/model versions.
- `render_report_html(report: dict) -> str` escapes all user-controlled content and emits print-ready HTML.
- `export_backup(audit: dict) -> dict` includes `formatVersion: 1`; `validate_backup(payload: dict) -> dict` rejects unknown versions and malformed structures before any database writes.
- Report API: `GET /api/audits/{id}/report`; backup API: `GET /api/audits/{id}/backup` and `POST /api/backups/import`. The report preview’s “Save as PDF” action opens the browser print dialog with the print stylesheet.

- [ ] **Step 1: Write failing report tests** for summary counts, incomplete pages, unresolved high-impact findings, manual coverage, certification disclaimer, escaping hostile labels/notes, and backup round-trip/invalid version.
- [ ] **Step 2: Run report tests** and verify expected failures.
- [ ] **Step 3: Implement report construction, print view, and backup validation/import** with strict field allowlists and no executable HTML from imported data; wire the report and backup endpoints and browser “Save as PDF” action.
- [ ] **Step 4: Run Python and Node report tests** and verify print rendering and backup round trip.
- [ ] **Step 5: Commit** as `feat: export client reports and audit backups`.

### Task 7: Install flow, documentation, and end-to-end verification

**Files:**
- Create: `Start AccessSprint.bat`
- Create: `README.md`
- Create: `tests-js/workflow.e2e.test.mjs`
- Modify: `.gitignore`

**Interfaces:**
- Launcher starts the app bound to loopback, opens `http://127.0.0.1:8000`, and keeps a visible server window for diagnostics.
- README documents prerequisites, `npm ci`, Chromium install, Python invocation, Ollama setup with `gemma4:e4b`, data location, privacy behavior, limits, backups, and the live smoke checklist.

- [ ] **Step 1: Write the end-to-end workflow test** for demo entry, audit creation, scan against a controlled local fixture, review a finding, complete a manual check, use offline Gemma state, export a report, and restore a JSON backup.
- [ ] **Step 2: Run the workflow test** and verify it fails because the launch/documentation flow is incomplete.
- [ ] **Step 3: Implement the launcher and docs**, including realistic troubleshooting for a missing Python executable, missing Chromium, offline Ollama, and absent `gemma4:e4b` tag.
- [ ] **Step 4: Run all automated checks**: `python -m unittest discover -v`, `npm test`, and the Playwright integration/workflow suite. Fix every failure.
- [ ] **Step 5: Perform live smoke checks** for local server health, Ollama model status and one real explanation if the model service is available, a permitted public website scan, report print preview, backup export/import, and localhost-only binding.
- [ ] **Step 6: Inspect the finished UI in a browser at desktop and mobile widths**, including keyboard navigation and reduced-motion behavior; correct visible issues.
- [ ] **Step 7: Commit** as `docs: finish AccessSprint setup and verification guide`.
- [ ] **Step 8: Create the GitHub repository `soniksharma/ASprints` and push the verified `main` branch**; confirm the remote repository URL and pushed commit SHA.

## Self-Review

- **Spec coverage:** Audit lifecycle and SQLite are Task 2; scanning and per-page errors are Task 3; API and local Gemma are Task 4; dark interactive UI and manual review are Task 5; reports, JSON portability, limitations and comparison are Tasks 2, 5, and 6; local-only privacy and safe input handling appear in Tasks 1, 3, and 4; Windows startup and validation are Task 7.
- **Step scan:** Each task follows failing test, expected red run, minimal implementation, green run, and local commit. The integration install steps depend on declared pinned packages and Chromium installation.
- **Type consistency:** The worker uses JSON files and receives normalized page URLs from `ScanService`; the API and frontend use JSON; audit and review status values match the spec; report data uses the same stored audit.
- **Review focus:** All five listed input/failure classes have named tests assigned to the owning task.
- **Proportion:** The plan is longer than the product spec because it fixes concrete interfaces and verification steps across the backend, scanner worker, UI, and report flow; it does not prescribe implementation bodies beyond the security-sensitive boundaries.


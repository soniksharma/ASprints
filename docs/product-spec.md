# AccessSprint Product Specification

**Status:** Approved prototype specification
**Date:** 2026-10-13  
**Product:** AccessSprint (repository: `ASprints`)

## Product goal

Help independent web developers and small accessibility consultancies deliver a useful, evidence-based first-pass accessibility audit to small businesses without paying for hosted AI or sending audit notes to a model provider.

AccessSprint is a local-first audit workspace. It combines repeatable browser checks with a human review workflow and a local Gemma assistant. Its output is a clear client report and a prioritized repair plan, not a claim of legal compliance or certification.

## User and problem

The primary user is a freelance web developer who wants to offer accessibility reviews as a paid, bounded service. They need to inspect a client website, translate technical findings into understandable fixes, track what they verified manually, and produce a professional deliverable. Existing automated scanners can produce raw rule output, but that output is often difficult to explain and easy to overstate. Hosted AI adds recurring cost and can expose client URLs, source snippets, or audit notes.

The client is a small business owner who needs to understand which issues matter, where they occur, what to fix first, and what still needs a person to check.

## Product promise

“Turn a website scan into a reviewed, client-ready accessibility action plan, with your audit data and AI assistance kept on your computer.”

## Core workflow

1. **Create an audit.** Enter a client/project name, website URL, auditor name, scope, and a small set of pages. The app explains that the user must have permission to test the site.
2. **Scan pages.** A local browser runner loads each allowed page and runs axe-core. The scan records rule IDs, impact, help text, affected element selectors, a short HTML excerpt, and page URL. Network failures and blocked pages are recorded as incomplete checks rather than silently counted as clean.
3. **Review evidence.** Findings are grouped by severity and rule. The user can inspect the affected element and evidence, mark each item as confirmed, needs review, fixed, or not applicable, and add a note. Automated results are explicitly labeled as leads for human review.
4. **Ask Gemma for an explanation.** The local Ollama model `gemma4:e4b` receives only the selected finding’s rule description, impact, and sanitized evidence needed to explain it. It returns a plain-language impact, a suggested repair, and a verification step. Gemma cannot add findings, change scanner severity, or mark an item fixed. If Ollama or the model is unavailable, the deterministic scan and manual workflow remain usable.
5. **Run manual checks.** A focused checklist covers keyboard-only navigation, visible focus, meaningful page title and headings, form labels and errors, zoom/reflow, and screen-reader spot checks. Each check has pass, issue, or not checked status plus an optional note. The report distinguishes manual checks from automated findings.
6. **Prepare and export a report.** Review an executive summary, scope and limitations, page coverage, prioritized findings, manual checks, and a practical next-step checklist. Export a print-ready PDF and JSON backup. The report includes scan time, tool/model details, and a clear statement that this is not a certification.
7. **Rescan after fixes.** Re-scan the same pages and compare finding counts and statuses with the prior run. Preserve prior reports and notes so the freelancer can demonstrate progress.

## MVP requirements

### Audit management

- Create, edit, archive, and delete local audits.
- Store audit metadata, page list, scan runs, findings, review states, manual checks, and report details in a local SQLite database.
- Provide a sample/demo audit so the interface can be explored before the user has a client site.
- Export and import a versioned JSON backup for portability.

### Website scanning

- Scan one to ten explicitly entered pages per run; do not crawl arbitrary links in the MVP.
- Accept HTTP and HTTPS URLs only. Resolve and reject localhost, private, link-local, and reserved IP destinations for the initial page, every redirect, and every browser subrequest; re-check DNS results to reduce SSRF risk.
- Limit response time, page count, response size, and concurrency. Surface blocked/failed pages and timeouts.
- Run Chromium and axe-core locally. Include the axe-core license and version in the repository and report.
- Keep scanner output as source of truth. Never describe automated checks as a complete WCAG evaluation.

### Local AI

- Default to exact Ollama model tag `gemma4:e4b`; provide a connection/model status indicator and a settings screen for the local Ollama base URL (loopback only) and model tag.
- Provide a “Test local model” action with actionable missing/Ollama-offline/model-not-found errors.
- Do not send audit data to a hosted service. Make the exact context sent to Gemma inspectable before or after each request.
- Validate the model response against a small structured schema; if parsing fails, show the raw answer as an explanation only and do not modify audit data.
- Keep user actions and findings independent of model availability.

### Reports and review

- Provide finding filters, status edits, notes, manual-check completion, and an audit timeline.
- Produce print-ready, client-facing reports with project branding and a freelancer identity field.
- Include limitations, unscanned pages, manual-check coverage, and unresolved high-impact findings.
- Provide a JSON data export suitable for backup and a human-readable PDF/print view.

### Interface

- Minimal, distinctive dark workspace with restrained terminal-inspired labels, green status accents, monospace details, and high-contrast readable body text.
- Interactive guided audit setup, visible scan progress, keyboard-accessible controls, clear empty/loading/error states, responsive desktop and mobile layouts.
- Include a first-run walkthrough and a safe demo project. The visual language must not make professional client reports look like a terminal.
- Meet basic accessibility expectations in the app itself: semantic structure, keyboard operation, visible focus, labels, reduced-motion support, and adequate contrast.

## Business model and validation

Start as a productized service: the freelancer uses AccessSprint to sell a fixed-scope accessibility review and prioritized repair plan. A later paid product could add reusable client portals, scheduled re-scans, branded templates, and team workflows. Do not build payments, subscriptions, multi-user accounts, or a cloud portal before validating demand.

Validation target: interview five freelance developers or small-business web maintainers, run three real audits with permission, and ask whether the report saves enough time to pay for. Track time to first report, report usefulness, number of findings manually corrected or dismissed, and willingness to pay.

## Open-source AI and hackathon fit

Gemma is a meaningful feature because it turns technical scanner evidence into a contextual explanation and verification step locally. The local model avoids per-audit API fees and allows client URLs, snippets, and reviewer notes to stay on the auditor’s machine. The deterministic scanner and human review remain the evidence source; the model helps with communication, not judgment.

The strongest target category is **Best Use of Gemma**. Other partner categories should be entered only if their technology becomes a substantive part of the product and can be demonstrated. Do not add partners as decorative integrations.

## Technical direction

- Local web application served only on loopback by a Python backend.
- Python 3 standard library HTTP API and SQLite storage for a low-friction local install; use a pinned local browser automation dependency only if the environment supports reliable installation.
- Playwright Chromium plus a locally packaged axe-core script for scans.
- Ollama chat API at loopback with the configured `gemma4:e4b` model.
- Browser frontend with a restrained, interactive dark interface and a print stylesheet for reports.
- Automated backend tests with mocked Ollama/browser boundaries, plus a documented live smoke checklist for local Ollama and a real permitted website.

## Safety, privacy, and limits

- The application binds to loopback and does not expose an unauthenticated service on the LAN.
- Treat target websites and page contents as untrusted. They cannot change system prompts, code execution, audit statuses, or report claims.
- Restrict scanning to explicitly supplied public URLs and apply the safe URL rules to redirects and browser subrequests, not just the first navigation.
- Store audit data only in a local application data directory and provide export/delete controls.
- Do not include credentials, cookies, or authenticated browser sessions in the MVP.
- Avoid legal advice and compliance guarantees. Reports state what was scanned, what was not checked, and that an expert review may still be required.

## Success criteria for the prototype

- A new user can create an audit and understand the first steps without instruction.
- A permitted public test site produces persisted axe findings or explicit per-page errors.
- The user can review findings, use the manual checklist, generate a Gemma explanation when the configured local model is available, and see useful errors when it is not.
- The user can export and re-open a backup and produce a readable client report.
- A rescan can be compared with an earlier scan.
- Automated tests cover URL validation, API validation, persistence, reporting data, and offline-model behavior.
- The app starts from a documented Windows launcher and binds only to localhost.

## Decisions that still need user review

1. Confirm the product and the one-to-ten-page local audit scope.
2. Confirm that the first release should be a local Windows-friendly web app, not a hosted SaaS.
3. Confirm that the findings report is an accessibility review aid and explicitly not a compliance certification.


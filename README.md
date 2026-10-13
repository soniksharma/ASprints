# AccessSprint

**Turn a website scan into a human-reviewed accessibility action plan.** AccessSprint is a local-first workspace for freelance developers who want to offer small, fixed-scope accessibility reviews. It runs Chromium and axe-core on your computer, keeps a person in charge of every finding, and can ask your local Gemma model to explain the evidence in plain language.

AccessSprint is an audit aid. It does not certify WCAG conformance or give legal advice.

## What you can do

- Create local client audits with one to ten explicit public pages. AccessSprint does not crawl links.
- Run axe-core in a local Playwright Chromium browser and keep a per-page result, including failures.
- Filter findings, inspect element evidence as text, record notes, and mark review status.
- Ask Ollama’s local `gemma4:e4b` model for an impact explanation, repair suggestion, and verification step. The exact bounded context is inspectable; model output cannot change findings or their review status.
- Record six hands-on checks, compare two scan runs, and see an audit activity timeline.
- Prepare a client-friendly print view, save it as PDF through the browser, and export or restore a versioned JSON backup.
- Explore a clearly labeled sample audit before adding client data.

## Windows setup

Prerequisites: Windows 10/11, Python 3.11 or newer, Node.js 20 or newer, and Ollama for local explanations. Gemma is optional for scanning and reports.

1. Open PowerShell in this folder and install the pinned packages:

   ```powershell
   npm ci
   npx playwright install chromium
   ```

2. Start Ollama and make sure the selected model is installed:

   ```powershell
   ollama pull gemma4:e4b
   ```

3. Double-click **Start AccessSprint.bat**. The launcher starts a visible local server window and opens `http://127.0.0.1:8000`.

If the launcher cannot find Python, install Python and enable the `py` launcher, or start it manually with `python main.py`. If Chromium is missing, run `npx playwright install chromium`. If Ollama is offline, scans and reports still work; start Ollama and choose **Test local model** under Model setup. If the `gemma4:e4b` tag is missing, run `ollama pull gemma4:e4b` and retry.

## Data and privacy

AccessSprint binds to the loopback interface (`127.0.0.1`) and stores its SQLite database under `%LOCALAPPDATA%\AccessSprint`. It does not include a hosted service or analytics. Scanner navigation, redirects, subrequests, and WebSockets are checked against public-address rules; local and private destinations are blocked. Only explicitly listed URLs are scanned. Do not enter credentials or authenticated pages.

Gemma runs through the Ollama server on loopback. For an explanation, AccessSprint sends the selected rule, impact, concise rule description, and bounded sanitized evidence. It omits the client name, project notes, and page HTML. Review the context inspector before relying on model text.

Keep JSON backups in a safe place before moving computers. Import creates a new audit and leaves the existing audit unchanged. Never import a backup you do not trust.

## Limits and report language

axe-core checks only some accessibility issues. Keyboard, screen-reader, zoom, form, and other human checks remain separate in the report. A scan covers only the pages and moment recorded. Review every item yourself and obtain permission before scanning a site. Reports state that they are not certifications or guarantees.

## Development and verification

```powershell
python -m unittest discover -v
npm test
```

The suite includes URL-policy tests, SQLite and API tests, Ollama response tests, real Chromium/axe fixtures, and a full browser workflow with an injected deterministic scanner. Run live checks on a permitted public site only after reviewing its scope. To start the app manually, use `python main.py`; pass `--port 8001` if port 8000 is already in use.

## Business model

AccessSprint is designed to support a service-first side hustle: sell a small, fixed-scope review and action plan, then rescan after the client makes fixes. The local model avoids per-report hosted AI fees and keeps client evidence on the auditor’s device. Validate pricing with real freelance developers and small businesses before building subscriptions or team features.

## License

AccessSprint is released under the MIT License. axe-core is included under its own license in [LICENSE-AXECORE.txt](LICENSE-AXECORE.txt); dependencies retain their respective licenses.

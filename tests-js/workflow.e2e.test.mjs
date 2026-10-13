import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import net from "node:net";
import { chromium } from "playwright";

const python = process.env.ASPRINT_PYTHON || "python";

async function freePort() {
  const socket = net.createServer();
  await new Promise((resolve, reject) => socket.listen(0, "127.0.0.1", resolve).once("error", reject));
  const { port } = socket.address();
  await new Promise(resolve => socket.close(resolve));
  return port;
}

test("desktop workflow creates, scans, reviews, reports, and restores an audit", { timeout: 90_000 }, async t => {
  const root = path.resolve(".");
  const temp = await mkdtemp(path.join(os.tmpdir(), "accesssprint-e2e-"));
  const port = await freePort();
  const serverSource = String.raw`
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from accesssprint.server import create_server
class Offline:
    def status(self): return {"available": False, "model_installed": False, "model": "gemma4:e4b", "message": "Ollama is offline for this test."}
    def test_connection(self): return {"available": False, "model": "gemma4:e4b", "message": "Ollama is offline for this test."}
    def explain_finding(self, finding): return {"error": "Ollama is offline for this test."}
def worker(payload, work_dir):
    return {"run_id": payload["runId"], "status": "completed", "axe_version": "4.14.0", "pages": [
      {"requested_url": url, "status": "ok", "final_url": url, "violations": [{
        "rule_id": "image-alt", "impact": "critical", "help": "Add alternative text",
        "description": "Images need text alternatives.", "help_url": "https://dequeuniversity.com/rules/axe/4.14/image-alt",
        "nodes": [{"target": ["img"], "html": "<img src=x>", "failure_summary": "The image lacks an alt attribute."}]}], "passes": 8, "incomplete": 1}
      for url in payload["pages"]]}
server = create_server("127.0.0.1", int(sys.argv[1]), data_dir=sys.argv[2], worker=worker, ollama_client=Offline())
try: server.serve_forever()
finally: server.close_application(); server.server_close()
`;
  let serverLogs = "";
  const child = spawn(python, ["-c", serverSource, String(port), path.join(temp, "data")], { cwd: root, windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
  child.stdout.on("data", chunk => { serverLogs += chunk.toString(); });
  child.stderr.on("data", chunk => { serverLogs += chunk.toString(); });
  const browser = await chromium.launch({ headless: true });
  t.after(async () => {
    await browser.close();
    const stopped = new Promise(resolve => child.once("exit", resolve));
    child.kill();
    await Promise.race([stopped, new Promise(resolve => setTimeout(resolve, 5000))]);
    await rm(temp, { recursive: true, force: true });
  });

  const page = await browser.newPage({ viewport: { width: 1365, height: 900 }, acceptDownloads: true, reducedMotion: "reduce" });
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  let ready = false;
  for (let i = 0; i < 60 && !ready; i++) {
    try { await page.goto(`http://127.0.0.1:${port}`, { waitUntil: "domcontentloaded", timeout: 1000 }); ready = true; }
    catch { await new Promise(resolve => setTimeout(resolve, 250)); }
  }
  assert.ok(ready, "local AccessSprint server should start");
  try { await page.getByRole("heading", { name: /make the web easier to use/i }).waitFor({ timeout: 5000 }); }
  catch { throw new Error(`Dashboard did not render. Page errors: ${pageErrors.join(" | ")}; server: ${serverLogs}; UI: ${await page.locator("body").innerText()}`); }
  assert.equal(await page.getByText("DEMO / SAMPLE").count(), 1);
  await page.getByRole("button", { name: /start a client audit/i }).click();
  await page.getByLabel("Project name").fill("Cafe review");
  await page.getByLabel("Client", { exact: true }).fill("Northstar Cafe");
  await page.getByLabel("Auditor name").fill("Sam Auditor");
  await page.getByLabel("Site address").fill("https://example.com");
  await page.getByLabel("Review scope").fill("Public home page review");
  await page.getByLabel(/Pages to scan/).fill("https://example.com/");
  await page.getByRole("button", { name: /create audit/i }).click();
  try { await page.getByRole("heading", { name: "Cafe review" }).waitFor({ timeout: 5000 }); }
  catch { throw new Error(`Audit creation did not reach the workspace. UI says: ${await page.locator("body").innerText()}`); }
  await page.getByRole("button", { name: "EDIT SCOPE" }).click();
  await page.getByLabel("Review scope").fill("Public home page and key flow review");
  await page.getByRole("button", { name: /save changes/i }).click();
  await page.locator(".page-head .lede").getByText("Public home page and key flow review").waitFor();
  await page.getByRole("button", { name: /run accessibility scan/i }).click();
  await page.getByText("Scan complete. Your findings are ready for human review.").waitFor({ timeout: 15_000 });
  await page.getByRole("tab", { name: "Findings" }).click();
  await page.locator(".finding-item").first().waitFor();
  await page.getByRole("button", { name: /ask gemma4:e4b/i }).click();
  await page.getByText("Ollama is offline for this test.").waitFor();
  await page.locator("#finding-status").selectOption("confirmed");
  await page.locator("#finding-note").fill("Checked against the client page.");
  await page.getByRole("button", { name: "SAVE REVIEW" }).click();
  await page.getByText("Review state saved locally.").waitFor();
  await page.getByRole("tab", { name: "Manual checks" }).click();
  const firstCheck = page.locator("[data-check-row]").first();
  await firstCheck.locator("select").selectOption("pass");
  await firstCheck.locator("input").fill("Keyboard order was checked.");
  await firstCheck.getByRole("button", { name: "SAVE" }).click();
  try { await page.getByText("Manual check saved.").waitFor({ timeout: 5000 }); }
  catch { throw new Error(`Manual check did not save. Toast: ${await page.locator("#toast").innerText()}; page: ${await page.locator("body").innerText()}`); }
  await page.getByRole("tab", { name: "Scan diff" }).click();
  await page.getByRole("button", { name: /run another scan/i }).click();
  await page.getByText("Scan complete. Your findings are ready for human review.").waitFor({ timeout: 15_000 });
  await page.getByRole("tab", { name: "Scan diff" }).click();
  await page.getByRole("button", { name: "COMPARE RUNS" }).click();
  await page.getByText("Resolved evidence").waitFor();
  await page.getByRole("tab", { name: "Client report" }).click();
  await page.getByRole("button", { name: "BUILD CLIENT REPORT" }).click();
  await page.getByRole("heading", { name: "Northstar Cafe" }).waitFor();
  await page.getByText("1/1").waitFor();
  await page.emulateMedia({ media: "print" });
  assert.equal(await page.locator(".sidebar").evaluate(element => getComputedStyle(element).display), "none");
  assert.equal(await page.locator(".report-sheet").evaluate(element => getComputedStyle(element).display), "block");
  await page.emulateMedia({ media: "screen" });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "EXPORT JSON BACKUP" }).click();
  const download = await downloadPromise;
  const backupPath = path.join(temp, "backup.json");
  await download.saveAs(backupPath);
  assert.match(download.suggestedFilename(), /accesssprint-cafe-review\.json/);
  await page.getByRole("button", { name: "Audits" }).click().catch(async () => page.locator(".brand").click());
  await page.getByRole("button", { name: "RESTORE JSON BACKUP" }).click();
  await page.locator("#backup-file").setInputFiles(backupPath);
  await page.getByRole("heading", { name: "Cafe review" }).waitFor({ timeout: 10_000 });
  await page.getByRole("button", { name: "ARCHIVE" }).click();
  await page.getByRole("heading", { name: "Archived / restore anytime" }).waitFor();
  await page.getByRole("button", { name: "RESTORE", exact: true }).click();
  await page.getByRole("button", { name: "OPEN AUDIT" }).first().waitFor();
  await page.getByRole("button", { name: /settings/i }).click().catch(async () => page.locator(".avatar-button").click());
  await page.getByText(/MODEL STATUS \/ OFFLINE/).waitFor();
  await page.getByRole("button", { name: /test local model/i }).click();
  await page.locator("#toast").getByText("Ollama is offline for this test.").waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "mobile layout should fit the viewport");
  await page.reload();
  await page.keyboard.press("Tab");
  assert.ok(await page.evaluate(() => document.activeElement.classList.contains("skip-link")), "keyboard focus should start at the skip link");
  assert.equal(await page.evaluate(() => matchMedia("(prefers-reduced-motion: reduce)").matches), true);
});

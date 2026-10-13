import { readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { chromium } from "playwright";
import { createRequestGuard, createWebSocketGuard } from "./policy.mjs";
import { normalizeAxeResults } from "./normalize.mjs";

const require = createRequire(import.meta.url);
const axePackage = require("axe-core/package.json");
const axeSource = await readFile(require.resolve("axe-core/axe.min.js"), "utf8");
const MAX_PAGES = 10;
const NAVIGATION_TIMEOUT_MS = 25_000;

export async function scanHtmlFixture(browser, html, source = axeSource) {
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await page.setContent(html, { waitUntil: "domcontentloaded", timeout: NAVIGATION_TIMEOUT_MS });
    await page.addScriptTag({ content: source });
    const result = await page.evaluate(async () => window.axe.run(document));
    return normalizeAxeResults(result, "https://fixture.invalid/");
  } finally {
    await context.close();
  }
}

async function scanPage(browser, pageUrl) {
  const context = await browser.newContext({ serviceWorkers: "block" });
  try {
    await context.routeWebSocket("**/*", createWebSocketGuard());
    const page = await context.newPage();
    await page.route("**/*", createRequestGuard());
    page.setDefaultNavigationTimeout(NAVIGATION_TIMEOUT_MS);
    page.setDefaultTimeout(NAVIGATION_TIMEOUT_MS);
    await page.goto(pageUrl, { waitUntil: "domcontentloaded" });
    await page.addScriptTag({ content: axeSource });
    const axeResult = await page.evaluate(async () => window.axe.run(document));
    return { status: "ok", final_url: page.url(), ...normalizeAxeResults(axeResult, page.url()) };
  } finally {
    await context.close();
  }
}

function pageError(error) {
  const message = String(error?.message || error || "Page could not be scanned.");
  const status = /timeout|timed out/i.test(message) ? "timeout" :
    /blockedbyclient|private or reserved|local network/i.test(message) ? "blocked" : "error";
  return { status, error: message.slice(0, 800), violations: [], passes: 0, incomplete: 1 };
}

export async function runScan(input, { launch = () => chromium.launch({ headless: true }) } = {}) {
  if (!input || !Array.isArray(input.pages) || input.pages.length < 1 || input.pages.length > MAX_PAGES) {
    throw new Error(`A scan must contain between 1 and ${MAX_PAGES} pages.`);
  }
  const browser = await launch();
  const pages = [];
  try {
    for (const pageUrl of input.pages) {
      try {
        pages.push({ requested_url: pageUrl, ...(await scanPage(browser, pageUrl)) });
      } catch (error) {
        pages.push({ requested_url: pageUrl, ...pageError(error) });
      }
    }
  } finally {
    await browser.close();
  }
  const successes = pages.filter(page => page.status === "ok").length;
  return {
    run_id: String(input.runId || "").slice(0, 100),
    status: successes === pages.length ? "completed" : successes > 0 ? "partial" : "failed",
    axe_version: axePackage.version,
    pages,
  };
}

async function main() {
  const [inputPath, outputPath] = process.argv.slice(2);
  if (!inputPath || !outputPath) throw new Error("Usage: node scanner/worker.mjs <input-json-path> <output-json-path>");
  const input = JSON.parse(await readFile(inputPath, "utf8"));
  const output = await runScan(input);
  await writeFile(outputPath, JSON.stringify(output), "utf8");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    process.stderr.write(`${error?.message || error}\n`);
    process.exitCode = 1;
  });
}

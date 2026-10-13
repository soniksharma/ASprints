import test from "node:test";
import assert from "node:assert/strict";
import { chromium } from "playwright";
import axe from "axe-core";
import { scanHtmlFixture } from "../scanner/worker.mjs";

test("local axe-core detects a known fixture issue and reports a clean fixture", async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const unsafe = await scanHtmlFixture(browser, "<html><body><img src='x'><h1></h1></body></html>", axe.source);
    const clean = await scanHtmlFixture(browser,
      "<html lang='en'><head><title>Audit fixture</title></head><body><h1>Welcome</h1><img src='x' alt='Product'></body></html>",
      axe.source);
    assert.ok(unsafe.violations.some(item => item.rule_id === "image-alt"));
    assert.equal(clean.violations.some(item => item.rule_id === "image-alt"), false);
  } finally {
    await browser.close();
  }
});


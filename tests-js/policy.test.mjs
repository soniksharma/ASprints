import test from "node:test";
import assert from "node:assert/strict";
import { assertPublicRequestUrl, createRequestGuard, createWebSocketGuard } from "../scanner/policy.mjs";

const publicLookup = async () => [{ address: "93.184.216.34", family: 4 }];

test("accepts a public HTTPS URL and resolves all DNS addresses", async () => {
  let lookedUp = "";
  const result = await assertPublicRequestUrl("https://example.com/home", {
    lookup: async (host, options) => { lookedUp = `${host}:${options.all}`; return publicLookup(); },
  });
  assert.equal(result.href, "https://example.com/home");
  assert.equal(lookedUp, "example.com:true");
});

test("rejects unsupported schemes, URL credentials, and local host names", async () => {
  for (const url of ["file:///tmp/site", "https://user:pass@example.com", "http://localhost/", "http://shop.local/"]) {
    await assert.rejects(assertPublicRequestUrl(url, { lookup: publicLookup }));
  }
});

test("rejects private literal IPs before DNS lookup", async () => {
  for (const url of ["http://127.0.0.1/", "http://10.0.0.2/", "http://[::1]/", "http://[fe80::1]/"]) {
    await assert.rejects(assertPublicRequestUrl(url, { lookup: publicLookup }));
  }
});

test("rejects a hostname if any resolved address is non-public", async () => {
  const lookup = async () => [
    { address: "93.184.216.34", family: 4 },
    { address: "192.168.1.9", family: 4 },
  ];
  await assert.rejects(assertPublicRequestUrl("https://example.com/", { lookup }));
});

test("blocks unsafe redirects and subrequests at the browser route boundary", async () => {
  for (const url of ["http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data"]) {
    let action = "";
    const route = {
      request: () => ({ url: () => url }),
      continue: async () => { action = "continued"; },
      abort: async reason => { action = `aborted:${reason}`; },
    };
    const guard = createRequestGuard({ lookup: publicLookup });
    await guard(route);
    assert.equal(action, "aborted:blockedbyclient");
  }
});

test("blocks private WebSocket destinations", async () => {
  let action = "";
  const socket = {
    url: () => "ws://127.0.0.1:3000/socket",
    connectToServer: () => { action = "connected"; },
    close: async options => { action = `closed:${options.code}`; },
  };
  await createWebSocketGuard({ lookup: publicLookup })(socket);
  assert.equal(action, "closed:1008");
});


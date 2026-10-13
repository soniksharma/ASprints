import { lookup as dnsLookup } from "node:dns/promises";
import ipaddr from "ipaddr.js";

const localSuffixes = [".localhost", ".local", ".internal", ".lan"];

export function isPublicAddress(address) {
  try {
    let parsed = ipaddr.parse(address);
    if (parsed.kind() === "ipv6" && parsed.isIPv4MappedAddress()) {
      parsed = parsed.toIPv4Address();
    }
    return parsed.range() === "unicast";
  } catch {
    return false;
  }
}

export async function assertPublicRequestUrl(input, { lookup = dnsLookup } = {}) {
  let url;
  try {
    url = new URL(input);
  } catch {
    throw new Error("The page request has an invalid URL.");
  }
  if (!new Set(["http:", "https:"]).has(url.protocol) || url.username || url.password) {
    throw new Error("Only credential-free HTTP and HTTPS requests are allowed.");
  }
  const hostname = url.hostname.replace(/^\[|\]$/g, "").toLowerCase().replace(/\.$/, "");
  if (!hostname || hostname === "localhost" || localSuffixes.some(suffix => hostname.endsWith(suffix))) {
    throw new Error("Requests to local network hosts are blocked.");
  }
  if (ipaddr.isValid(hostname)) {
    if (!isPublicAddress(hostname)) throw new Error("Requests to private or reserved addresses are blocked.");
    return url;
  }
  if (!hostname.includes(".")) throw new Error("Requests to local network hosts are blocked.");
  let addresses;
  try {
    addresses = await lookup(hostname, { all: true, verbatim: true });
  } catch {
    throw new Error("The host could not be resolved safely.");
  }
  if (!Array.isArray(addresses) || addresses.length === 0 || addresses.some(item => !isPublicAddress(item.address))) {
    throw new Error("The host resolves to a private or reserved address, so the request was blocked.");
  }
  return url;
}

export function createRequestGuard({ lookup = dnsLookup, onBlocked = () => {} } = {}) {
  return async route => {
    const requestUrl = route.request().url();
    try {
      await assertPublicRequestUrl(requestUrl, { lookup });
      await route.continue();
    } catch (error) {
      try { onBlocked(requestUrl, error); } catch { /* diagnostics must not bypass the block */ }
      await route.abort("blockedbyclient");
    }
  };
}

export function createWebSocketGuard({ lookup = dnsLookup, onBlocked = () => {} } = {}) {
  return async socket => {
    const socketUrl = socket.url();
    const httpUrl = socketUrl.replace(/^ws:/i, "http:").replace(/^wss:/i, "https:");
    try {
      await assertPublicRequestUrl(httpUrl, { lookup });
      socket.connectToServer();
    } catch (error) {
      try { onBlocked(socketUrl, error); } catch { /* diagnostics must not bypass the block */ }
      await socket.close({ code: 1008, reason: "Local or unsafe WebSocket destination blocked" });
    }
  };
}

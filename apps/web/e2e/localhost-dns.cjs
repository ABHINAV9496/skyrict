/*
 * Make Node's DNS resolve `*.localhost` to loopback, like Chromium and
 * RFC 6761 do. Playwright's APIRequestContext (used by BffApi) resolves
 * requests through Node, and on Windows `getaddrinfo` does not know
 * `.localhost` - the E2E origin is http://default.localhost:3000, which
 * nginx serves on 127.0.0.1. Loaded by playwright.config.ts before any
 * request is made. This is a no-op on Linux CI where systemd-resolved
 * already maps `.localhost` to loopback.
 */
const dns = require("node:dns");

const originalLookup = dns.lookup;
const originalPromisesLookup = dns.promises.lookup;

function isLocalhostHost(hostname) {
  return typeof hostname === "string" && hostname.toLowerCase().endsWith(".localhost");
}

function familyOf(options) {
  if (typeof options === "number") return options;
  if (options && typeof options === "object") return options.family ?? 4;
  return 4;
}

dns.lookup = function localhostLookup(hostname, options, callback) {
  const hasOptions = typeof options === "object" || typeof options === "number";
  const cb = hasOptions ? callback : options;

  if (!isLocalhostHost(hostname) || typeof cb !== "function") {
    return hasOptions ? originalLookup(hostname, options, callback) : originalLookup(hostname, options);
  }

  const optionsObject = hasOptions && typeof options === "object" ? options : undefined;
  const record =
    familyOf(optionsObject ?? options) === 6
      ? { address: "::1", family: 6 }
      : { address: "127.0.0.1", family: 4 };
  process.nextTick(() => {
    if (optionsObject?.all) {
      cb(null, [record]);
    } else {
      cb(null, record.address, record.family);
    }
  });
};

dns.promises.lookup = function localhostPromisesLookup(hostname, options) {
  if (!isLocalhostHost(hostname)) return originalPromisesLookup.call(dns.promises, hostname, options);
  const record =
    familyOf(options) === 6
      ? { address: "::1", family: 6 }
      : { address: "127.0.0.1", family: 4 };
  const all = Boolean(options && typeof options === "object" && options.all);
  return Promise.resolve(all ? [record] : record);
};
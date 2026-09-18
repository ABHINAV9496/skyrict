// CI bundle budget gate: compares a fresh `next build` route table against the
// committed baseline (scripts/perf/perf-baseline.json). Fails if any budgeted
// route's First Load JS (gzip) exceeds the baseline value.
//
// Usage: node scripts/perf/assert-bundle-sizes.mjs --log <next-build.log>
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const argv = process.argv.slice(2);
const logArg = argv[argv.indexOf("--log") + 1];
if (!logArg) {
  console.error("usage: node scripts/perf/assert-bundle-sizes.mjs --log <next-build.log>");
  process.exit(1);
}

const baselinePath = path.join(path.dirname(fileURLToPath(import.meta.url)), "perf-baseline.json");
const baseline = JSON.parse(fs.readFileSync(baselinePath, "utf8"));
const budget = Object.fromEntries(baseline.routes.map((r) => [r.route, r.firstLoadKb]));

const buf = fs.readFileSync(logArg);
const log = buf.toString(buf[0] === 0xff && buf[1] === 0xfe ? "utf16le" : "utf8").replace(/\x1B\[[0-9;]*[a-zA-Z]/g, "");

const routeRe = /^[┌├└]\s+[ƒ○]\s+(\S+)\s+([\d.]+) kB\s+([\d.]+) kB$/;
const seen = {};
for (const line of log.split(/\r?\n/)) {
  const m = line.match(routeRe);
  if (m && budget[m[1]] !== undefined) seen[m[1]] = parseFloat(m[3]);
}

const failures = Object.keys(budget).filter((r) => seen[r] === undefined || seen[r] > budget[r]);

if (failures.length > 0) {
  console.error("BUNDLE BUDGET FAILED");
  for (const r of failures) {
    console.error(`  ${r}: current ${seen[r]} kB > baseline ${budget[r]} kB`);
  }
  process.exit(1);
}
console.log(`bundle budget OK (${Object.keys(seen).length}/${Object.keys(budget).length} budgeted routes verified)`);
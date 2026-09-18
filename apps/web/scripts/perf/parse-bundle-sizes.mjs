// Parses a `next build` log + (optional) bundle-analyzer client.html into the
// bundle-size baseline: per-route first-load JS (gzip, as Next prints it) and
// the largest client chunks by gzip. Emits JSON; also renders a markdown table.
//
// Usage:
//   node scripts/perf/parse-bundle-sizes.mjs --log build.log [--analyze .next/analyze/client.html]
import fs from "node:fs";
import path from "node:path";

const argv = process.argv.slice(2);
function arg(name, fallback) {
  const i = argv.indexOf(name);
  return i === -1 ? fallback : argv[i + 1];
}
const logPath = arg("--log", null);
const analyzePath = arg("--analyze", null);
if (!logPath) {
  console.error("usage: node scripts/perf/parse-bundle-sizes.mjs --log <next-build.log> [--analyze <client.html>]");
  process.exit(1);
}

const buf = fs.readFileSync(logPath);
// Windows PowerShell Tee-Object/Out-File write UTF-16LE; detect and decode.
const isUtf16 = buf[0] === 0xff && buf[1] === 0xfe;
const log = buf.toString(isUtf16 ? "utf16le" : "utf8").replace(/\x1B\[[0-9;]*[a-zA-Z]/g, "");
const parsed = { routes: [], sharedFirstLoadKb: null, topChunks: [], sourceLog: path.basename(logPath) };

const routeRe = /^[┌├└]\s+[ƒ○]\s+(\S+)\s+([\d.]+) kB\s+([\d.]+) kB$/;
for (const line of log.split(/\r?\n/)) {
  const m = line.match(routeRe);
  if (m && !m[1].startsWith("chunks/") && !m[1].startsWith("/api/")) {
    parsed.routes.push({ route: m[1], sizeKb: parseFloat(m[2]), firstLoadKb: parseFloat(m[3]) });
  }
  const shared = line.match(/First Load JS shared by all\s+([\d.]+) kB/);
  if (shared) parsed.sharedFirstLoadKb = parseFloat(shared[1]);
}

if (analyzePath && fs.existsSync(analyzePath)) {
  const html = fs.readFileSync(analyzePath, "utf8");
  const m = html.match(/window\.chartData = (\[.{0,2000000}?\]);/s);
  if (m) {
    const chunks = JSON.parse(m[1])
      .filter((c) => c.isAsset && !c.label.includes("app/"))
      .sort((a, b) => b.gzipSize - a.gzipSize)
      .slice(0, 15);
    parsed.topChunks = chunks.map((c) => ({ label: c.label, gzip: c.gzipSize, parsed: c.parsedSize }));
  }
}

console.log(JSON.stringify(parsed, null, 2));

if (process.env.RENDER_MARKDOWN === "1") {
  const md = [
    "| Route | Size | First Load JS (gzip) |",
    "|---|---:|---:|",
    ...parsed.routes.map((r) => `| ${r.route} | ${r.sizeKb} kB | ${r.firstLoadKb} kB |`),
    "",
    `Shared by all routes: **${parsed.sharedFirstLoadKb} kB** (gzip).`,
  ].join("\n");
  fs.writeFileSync(path.join(path.dirname(logPath), "bundle-table.md"), md);
  console.error("\nwrote bundle-table.md next to the log");
}
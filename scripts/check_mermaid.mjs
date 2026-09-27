// Parse every mermaid block in the given markdown files with mermaid itself.
//
// A static linter can only catch the mistakes you already know about; this
// catches the rest. Needs a node install with mermaid + jsdom:
//
//   npm --prefix .mermaid-check install mermaid jsdom
//   LECGAP_MERMAID_DIR=.mermaid-check node scripts/check_mermaid.mjs README.md
//
// pytest drives this for you (see tests/test_docs_render.py); the mermaid
// install is resolved from LECGAP_MERMAID_DIR rather than from this file's own
// location, so a throwaway install anywhere on the machine works.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";

const dir = process.env.LECGAP_MERMAID_DIR;
if (!dir) {
  console.error("set LECGAP_MERMAID_DIR to a directory whose node_modules has mermaid");
  process.exit(2);
}
// Both packages are resolved through the *install* directory rather than this
// file's location, so a throwaway `npm --prefix` install anywhere works and the
// script itself stays dependency-free in the repo.
const req = createRequire(resolve(dir, "noop.js"));
const load = (name) => import(pathToFileURL(req.resolve(name)).href);

const { JSDOM } = await load("jsdom");
const dom = new JSDOM("<!doctype html><html><body></body></html>");
global.window = dom.window;
global.document = dom.window.document;
Object.defineProperty(global, "navigator", {
  value: dom.window.navigator,
  configurable: true,
});

const mermaid = (await load("mermaid")).default;
mermaid.initialize({ startOnLoad: false, securityLevel: "loose" });

let bad = 0;
let seen = 0;
for (const file of process.argv.slice(2)) {
  const md = readFileSync(file, "utf8");
  const blocks = [...md.matchAll(/```mermaid\r?\n([\s\S]*?)```/g)];
  for (const [i, block] of blocks.entries()) {
    seen += 1;
    const lines = block[1].split("\n");
    try {
      await mermaid.parse(block[1]);
      console.log(`OK   ${file} block#${i + 1} (${lines.length} lines)`);
    } catch (err) {
      bad += 1;
      const text = String(err?.message ?? err);
      console.log(`FAIL ${file} block#${i + 1}: ${text.split("\n")[0]}`);
      const m = /line (\d+)/.exec(text);
      if (m) console.log(`     near: ${lines[Number(m[1]) - 1] ?? ""}`);
    }
  }
}
console.log(`${seen - bad}/${seen} mermaid blocks parse`);
process.exit(bad ? 1 : 0);

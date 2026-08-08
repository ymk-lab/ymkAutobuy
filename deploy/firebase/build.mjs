#!/usr/bin/env node
/**
 * Build static Structure Gate UI for Firebase Hosting.
 *
 * Env:
 *   QRESEARCH_API_BASE  Backend origin, e.g. https://xxx.trycloudflare.com
 *                       Leave empty only for local same-origin testing.
 */
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(__dirname, "..", "..");
const srcStatic = join(repoRoot, "src", "qresearch", "web", "static");
const publicDir = join(__dirname, "public");
const publicStatic = join(publicDir, "static");

const apiBase = String(process.env.QRESEARCH_API_BASE || "")
  .trim()
  .replace(/\/$/, "");

rmSync(publicDir, { recursive: true, force: true });
mkdirSync(publicStatic, { recursive: true });
cpSync(srcStatic, publicStatic, { recursive: true });

// Host index at site root (Firebase public/).
const indexSrc = join(srcStatic, "index.html");
let html = readFileSync(indexSrc, "utf8");
// Ensure config.js loads before app JS (already in template).
writeFileSync(join(publicDir, "index.html"), html);

const safe = apiBase.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
writeFileSync(
  join(publicDir, "config.js"),
  `window.QRESEARCH_API_BASE = "${safe}";\n`,
  "utf8"
);

writeFileSync(
  join(publicDir, "404.html"),
  `<!DOCTYPE html><html lang="zh-Hant"><meta charset="utf-8"/><title>Not found</title>
<meta http-equiv="refresh" content="0;url=/" />
<p><a href="/">Structure Gate</a></p>`,
  "utf8"
);

console.log(`[firebase-build] public=${publicDir}`);
console.log(
  `[firebase-build] QRESEARCH_API_BASE=${apiBase || "(empty = same-origin /api via Cloud Run rewrite or in-page tunnel)"}`
);

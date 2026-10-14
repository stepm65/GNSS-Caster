// Isolated local preview. Never forwards requests to a real caster.
import { createServer } from "node:http";
import { readFileSync, existsSync } from "node:fs";
import { resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import { fixture, station } from "./tests/fixtures.mjs";

const root = fileURLToPath(new URL(".", import.meta.url)),
  dist = resolve(root, "dist");
const manifest = JSON.parse(
  readFileSync(resolve(dist, ".vite/manifest.json"), "utf8"),
);
const entry = manifest["src/main.jsx"].file;
const port = Number(process.env.PORT || 5173);
createServer(async (req, res) => {
  const url = new URL(req.url, "http://127.0.0.1");
  res.setHeader("Cache-Control", "no-store");
  res.setHeader(
    "Content-Security-Policy",
    "default-src 'self'; script-src 'self' 'nonce-local-preview'; script-src-attr 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'",
  );
  if (url.pathname.startsWith("/static/ui/")) {
    const path = resolve(dist, url.pathname.slice("/static/ui/".length));
    if (!path.startsWith(dist + sep) || !existsSync(path)) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.setHeader(
      "Content-Type",
      path.endsWith(".js") ? "text/javascript" : "text/css",
    );
    res.end(readFileSync(path));
    return;
  }
  if (url.pathname.startsWith("/api/")) {
    res.setHeader("Content-Type", "application/json");
    if (req.method !== "GET") {
      req.resume();
      res.writeHead(409);
      res.end(
        JSON.stringify({
          error: "Preview only: no real settings or hardware are changed.",
        }),
      );
      return;
    }
    const data = fixture(url.pathname);
    if (data === undefined) {
      res.writeHead(404);
      res.end(JSON.stringify({ error: "Preview endpoint not configured" }));
      return;
    }
    res.end(JSON.stringify(data));
    return;
  }
  const boot = {
    username: "admin",
    userId: 1,
    role: url.searchParams.get("role") || "admin",
    version: "3.1.0",
    preview: true,
    messages: [],
    error: null,
  };
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  res.end(
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="csrf-token" content="preview-csrf"><meta name="csp-nonce" content="local-preview"><link rel="icon" href="data:,"><title>GNSS Caster · Preview</title></head><body><div id="root"></div><script nonce="local-preview" id="gnss-bootstrap" type="application/json">${JSON.stringify(boot).replaceAll("<", "\\u003c")}</script><script nonce="local-preview" type="module" src="/static/ui/${entry}"></script></body></html>`,
  );
}).listen(port, "127.0.0.1", () =>
  process.stdout.write(
    `Preview: http://127.0.0.1:${port}/dashboard (sample data only)\n`,
  ),
);

// Build the AYVIA network page into dist/:
//   dist/network.html, dist/network-config.js, dist/assets/ayvia-network-<hash>.js
import { build } from "esbuild";
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync, copyFileSync, rmSync } from "node:fs";

rmSync("dist", { recursive: true, force: true });
mkdirSync("dist/assets", { recursive: true });

const out = await build({
  entryPoints: ["src/main.js"],
  bundle: true,
  format: "esm",
  platform: "browser",
  target: ["es2020"],
  minify: true,
  write: false,
  define: { "process.env.NODE_ENV": '"production"', global: "globalThis" },
  logLevel: "warning",
});
const code = out.outputFiles[0].contents;
const hash = createHash("sha256").update(code).digest("hex").slice(0, 10);
const jsName = `assets/ayvia-network-${hash}.js`;
writeFileSync(`dist/${jsName}`, code);
writeFileSync("dist/network.html", readFileSync("src/network.html", "utf8").replace("__APP_JS__", "/" + jsName));
copyFileSync("public/network-config.js", "dist/network-config.js");
console.log(`built dist/network.html + dist/${jsName} (${(code.length / 1024).toFixed(0)} KB)`);

// Renders index.html to an MP4 (1080x1920, 30fps) frame by frame.
// Usage: node render.mjs [out.mp4] [--stills]
//   needs playwright (npm i -g playwright) and ffmpeg on PATH (or FFMPEG env var)
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright"); }
catch { playwright = require(path.join(process.execPath, "../../lib/node_modules/playwright")); }

const dir = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const out = path.resolve(args.find(a => !a.startsWith("--")) ?? path.join(dir, "saudifitx-focus-14.mp4"));
const stills = args.includes("--stills");
const FPS = 30;
const ffmpeg = process.env.FFMPEG ?? "ffmpeg";

const browser = await playwright.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
await page.goto(pathToFileURL(path.join(dir, "index.html")).href + "?capture");
await page.waitForFunction(() => window.ready === true);
const duration = await page.evaluate(() => window.DURATION);
const stage = page.locator("#stage");

if (stills) {
  for (const t of [1.55, 5.2, 8.8, 13.6, 16.4, 19.6]) {
    await page.evaluate(t => window.render(t), t);
    await stage.screenshot({ path: path.join(process.env.STILLS_DIR ?? dir, `still-${t}.png`) });
  }
  await browser.close();
  process.exit(0);
}

const ff = spawn(ffmpeg, [
  "-y", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
  "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium",
  "-movflags", "+faststart", out,
], { stdio: ["pipe", "ignore", "inherit"] });

const total = Math.round(duration * FPS);
for (let f = 0; f <= total; f++) {
  await page.evaluate(t => window.render(t), f / FPS);
  const buf = await stage.screenshot({ type: "jpeg", quality: 95 });
  if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once("drain", r));
  if (f % 60 === 0) process.stdout.write(`\rframe ${f}/${total}`);
}
ff.stdin.end();
await new Promise(r => ff.on("close", r));
await browser.close();
console.log(`\nwrote ${out}`);

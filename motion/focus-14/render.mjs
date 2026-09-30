// Renders index.html frame by frame through window.seek(t).
//   node render.mjs                 → saudifitx-focus-14.mp4 (1080x1920, 30fps, H.264 yuv420p CRF 16, AAC score)
//   node render.mjs --sheet [dir]   → contact sheet, one frame per measured beat (sheet.png)
// Needs playwright and ffmpeg (on PATH or $FFMPEG). Run `python3 score.py` first for score.wav + beats.json.
import { createRequire } from "node:module";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
let playwright;
try { playwright = require("playwright"); }
catch { playwright = require(path.join(process.execPath, "../../lib/node_modules/playwright")); }

const dir = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const sheet = args.includes("--sheet");
const positional = args.filter(a => !a.startsWith("--"));
const FPS = 30;
const ffmpeg = process.env.FFMPEG ?? "ffmpeg";
const run = (argv, stdin) => new Promise((ok, fail) => {
  const p = spawn(ffmpeg, argv, { stdio: [stdin ? "pipe" : "ignore", "ignore", "inherit"] });
  p.on("close", c => c === 0 ? ok() : fail(new Error(`ffmpeg exited ${c}`)));
  if (stdin) stdin(p);
});

// static server so fetch("beats.json") works
const types = { ".html": "text/html", ".json": "application/json", ".png": "image/png", ".ttf": "font/ttf", ".wav": "audio/wav", ".js": "text/javascript" };
const server = createServer(async (req, res) => {
  try {
    const f = path.join(dir, decodeURIComponent(new URL(req.url, "http://x").pathname));
    if (!f.startsWith(dir)) throw 0;
    res.writeHead(200, { "content-type": types[path.extname(f)] ?? "application/octet-stream" });
    res.end(await readFile(f.endsWith(path.sep) ? path.join(f, "index.html") : f));
  } catch { res.writeHead(404); res.end(); }
}).listen(0);
const port = server.address().port;

const browser = await playwright.chromium.launch();
const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
await page.goto(`http://127.0.0.1:${port}/index.html?capture`);
await page.waitForFunction(() => window.ready === true);
const { duration, beats } = await page.evaluate(() => ({ duration: window.DURATION, beats: window.BEATS }));
const stage = page.locator("#stage");
const shot = async t => { await page.evaluate(t => window.seek(t), t); return stage.screenshot({ type: "png" }); };

if (sheet) {
  // one frame per beat, sampled an 8th note after the beat so each hit has landed
  const out = path.resolve(positional[0] ?? dir);
  const tmp = path.join(out, ".sheet-frames");
  await rm(tmp, { recursive: true, force: true }); await mkdir(tmp, { recursive: true });
  const step = beats[1] - beats[0];
  for (let i = 0; i < beats.length; i++) {
    const t = Math.min(beats[i] + step / 2, duration - 1 / FPS);
    await writeFile(path.join(tmp, `b${String(i).padStart(2, "0")}.png`), await shot(t));
  }
  await run(["-y", "-loglevel", "error", "-framerate", "1", "-i", path.join(tmp, "b%02d.png"),
    "-vf", "scale=270:480,tile=8x5:padding=6:color=black",
    "-frames:v", "1", path.join(out, "sheet.png")]);
  await rm(tmp, { recursive: true, force: true });
  console.log(`wrote ${path.join(out, "sheet.png")} (${beats.length} beats)`);
} else {
  const out = path.resolve(positional[0] ?? path.join(dir, "saudifitx-focus-14.mp4"));
  const total = Math.round(duration * FPS);
  await run([
    "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
    "-i", path.join(dir, "score.wav"),
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow",
    "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", out,
  ], async p => {
    for (let f = 0; f < total; f++) {
      if (!p.stdin.write(await shot(f / FPS))) await new Promise(r => p.stdin.once("drain", r));
      if (f % 60 === 0) process.stdout.write(`\rframe ${f}/${total}`);
    }
    p.stdin.end();
  });
  console.log(`\nwrote ${out}`);
}
await browser.close();
server.close();

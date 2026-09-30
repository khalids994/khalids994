// Renders index.html frame by frame through window.seek(t).
//   node render.mjs                 → saudifitx-focus-14.mp4 (1080x1920, 60fps, 2× supersampled, H.264 yuv420p BT.709 CRF 16, AAC score)
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
const FPS = Number(process.env.FPS ?? 60);
const SS = Number(process.env.SS ?? 2);          // supersampling: render at SS× and downscale (smoother text edges)
const WORKERS = Number(process.env.WORKERS ?? 4); // parallel pages — safe because seek(t) is pure
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
const openPage = async scale => {
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: scale });
  await page.goto(`http://127.0.0.1:${port}/index.html?capture`);
  await page.waitForFunction(() => window.ready === true);
  const stage = page.locator("#stage");
  return { page, shot: async (t, type = "png") => { await page.evaluate(t => window.seek(t), t); return stage.screenshot(type === "png" ? { type } : { type, quality: 100 }); } };
};
const main = await openPage(1);
const { duration, beats } = await main.page.evaluate(() => ({ duration: window.DURATION, beats: window.BEATS }));
const shot = main.shot;

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
    "-vf", `scale=270:480,tile=8x${Math.ceil(beats.length / 8)}:padding=6:color=black`,
    "-frames:v", "1", path.join(out, "sheet.png")]);
  await rm(tmp, { recursive: true, force: true });
  console.log(`wrote ${path.join(out, "sheet.png")} (${beats.length} beats)`);
} else {
  const out = path.resolve(positional[0] ?? path.join(dir, "saudifitx-focus-14.mp4"));
  const total = Math.round(duration * FPS);
  const pages = await Promise.all(Array.from({ length: WORKERS }, () => openPage(SS)));
  await run([
    "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-i", "-",
    "-i", path.join(dir, "score.wav"),
    // downscale the SS× frames with lanczos; convert RGB→YUV with the BT.709 matrix and tag it,
    // so phones decode the brand greens correctly (untagged BT.601 shifts them)
    "-vf", "scale=1080:1920:flags=lanczos+accurate_rnd+full_chroma_int:out_color_matrix=bt709:out_range=tv,format=yuv420p",
    "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
    "-c:v", "libx264", "-profile:v", "high", "-crf", "16", "-preset", "slow", "-tune", "animation",
    "-x264-params", "aq-mode=3:aq-strength=1.0",                 // spend bits on flat gradients: less banding
    "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", out,
  ], async p => {
    for (let f = 0; f < total; f += WORKERS) {
      const batch = await Promise.all(pages.map((pg, w) => f + w < total ? pg.shot((f + w) / FPS, "jpeg") : null));
      for (const buf of batch) if (buf && !p.stdin.write(buf)) await new Promise(r => p.stdin.once("drain", r));
      if (f % 120 < WORKERS) process.stdout.write(`\rframe ${f}/${total}`);
    }
    p.stdin.end();
  });
  console.log(`\nwrote ${out}`);
}
await browser.close();
server.close();

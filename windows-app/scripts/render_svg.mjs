// SVG → PNG mit Chromium (Playwright): Verläufe, Schatten (feDropShadow) und Schrift (Inter) genau wie im Entwurf.
// Aufruf über make_icons.py:  node render_svg.mjs <auftrag.json>
// auftrag.json: [{"svg": "<Pfad>", "size": 32, "out": "<Pfad>.png"}, …] – transparenter Hintergrund.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const jobs = JSON.parse(readFileSync(process.argv[2], "utf8"));
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ deviceScaleFactor: 1 });
  for (const job of jobs) {
    const svg = readFileSync(job.svg, "utf8");
    await page.setViewportSize({ width: job.size, height: job.size });
    await page.setContent(
      `<html><body style="margin:0;background:transparent">` +
        `<div style="width:${job.size}px;height:${job.size}px">${svg.replace("<svg ", `<svg width="${job.size}" height="${job.size}" `)}</div>` +
        `</body></html>`,
    );
    await page.evaluate(() => document.fonts.ready);
    await page.locator("div").screenshot({ path: job.out, omitBackground: true });
  }
} finally {
  await browser.close();
}

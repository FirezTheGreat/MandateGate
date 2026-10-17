// One-off (deleted after use): grab frames from the recorded video into a contact sheet.
import { chromium } from "@playwright/test";
import { writeFileSync, rmSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, dirname, join, basename } from "node:path";

const [video, out] = process.argv.slice(2);
const times = [3, 10, 22, 32, 47, 57, 72, 97, 112, 122, 132, 143];
const html = join(dirname(resolve(video)), "_frames.html");
writeFileSync(html, `<body style="margin:0;background:#000;display:grid;grid-template-columns:repeat(4,683px)">
${times.map((t) => `<div style="position:relative"><video muted preload="auto" src="${basename(video)}#t=${t}" style="width:683px;height:384px;display:block"></video><span style="position:absolute;left:4px;top:2px;color:#ff0;font:bold 18px sans-serif">${t}s</span></div>`).join("")}</body>`);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 683 * 4, height: 384 * 3 } });
try {
  await page.goto(pathToFileURL(html).href);
  await page.waitForFunction(() => [...document.querySelectorAll("video")].every((v) => v.readyState >= 2), null, { timeout: 60000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: out });
  console.log("duration", await page.evaluate(() => document.querySelector("video").duration));
} finally {
  await browser.close();
  rmSync(html, { force: true });
}

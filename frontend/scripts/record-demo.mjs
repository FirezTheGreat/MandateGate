// Backup demo video (ROADMAP Phase 7): drives the real dashboard through the demo script and records it
// at projector size, with on-screen captions so it stands on its own without narration.
//
//   make dev            (gate, payment service, dashboard; .env with an AI key for the real-AI steps)
//   npm run video       → video/mandategate-demo.webm  (about 2.5 minutes)
import { chromium } from "@playwright/test";
import { mkdirSync, readdirSync, renameSync, rmSync } from "node:fs";
import { join } from "node:path";

const URL = process.env.DASHBOARD_URL ?? "http://localhost:5173/";
const OUT = "video";
const SIZE = { width: 1366, height: 768 };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

/** A caption bar over the header (pointer-events: none, so clicks pass through). */
async function caption(page, title, line = "") {
  await page.evaluate(([t, l]) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      el.style.cssText = [
        "position:fixed", "left:24px", "top:10px", "z-index:99999", "max-width:900px", "pointer-events:none",
        "padding:12px 18px", "border-radius:14px", "background:rgba(5,9,21,.94)", "border:1px solid #86a0ff",
        "box-shadow:0 10px 40px rgba(0,0,0,.5)", "font-family:'IBM Plex Sans',system-ui,sans-serif", "color:#eaf0fb",
        "transition:opacity .25s",
      ].join(";");
      document.body.appendChild(el);
    }
    el.style.opacity = "0";
    setTimeout(() => {
      el.innerHTML = `<div style="font:800 22px/1.2 'Archivo Variable',sans-serif;font-stretch:112%">${t}</div>` +
        (l ? `<div style="margin-top:4px;font-size:16px;color:#9ba7c5">${l}</div>` : "");
      el.style.opacity = "1";
    }, 250);
  }, [title, line]);
  await wait(300);
}

async function reset(page) {
  await page.getByRole("button", { name: "Reset demo" }).click();
  await page.getByText("Nothing yet: run a scenario").waitFor();
}

async function protection(page, on) {
  await page.getByRole("button", { name: on ? "With MandateGate" : "Without MandateGate", exact: true }).click();
  await page.getByText(on ? "MandateGate on" : "MandateGate off", { exact: true }).waitFor();
}

const stamp = (page, text) => page.getByRole("status").filter({ hasText: text });

async function scrollTo(page, y) {
  await page.evaluate((top) => window.scrollTo({ top, behavior: "smooth" }), y);
  await wait(900);
}

mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: SIZE, recordVideo: { dir: OUT, size: SIZE } });
const page = await context.newPage();
page.setDefaultTimeout(120_000);

try {
  await page.goto(URL);
  await page.getByText("Live", { exact: true }).waitFor();
  await reset(page);
  await protection(page, false);

  // 1. Hook
  await caption(page, "AI agents can now pay invoices.", "Watch what happens when one reads the wrong email.");
  await wait(4500);

  // 2. Baseline attack (the mandate bar fills in once the run creates its approval)
  await page.getByRole("button", { name: /Scam email/ }).click();
  await page.getByText("Attacker paid").first().waitFor();
  await caption(page, "The human approved exactly one thing", "Top bar: pay Acme's invoice INV-1048, up to ₹5,000. The payee must come from the vendor registry.");
  await wait(5500);
  await caption(page, "Without MandateGate, the agent read a fake email", "A simulated agent, scripted to fall for scams, believed a bank-change email from acme-supp1ies.com.");
  await wait(5500);
  await caption(page, "Every ordinary check passed", "Right agent, right tool, right invoice, under the limit. And ₹4,850 went to EVE-777.");
  await wait(5000);
  await scrollTo(page, 760);
  await caption(page, "The money actually moved", "The ledger shows the payment to the attacker's account.");
  await wait(4000);
  await scrollTo(page, 0);

  // 3. MandateGate on
  await reset(page);
  await protection(page, true);
  await caption(page, "With MandateGate: same agent, same email");
  await page.getByRole("button", { name: /Scam email/ }).click();
  await stamp(page, "BLOCKED").waitFor();
  await wait(1200);
  await caption(page, "BLOCKED: the payee never came from the vendor registry", "MandateGate traced EVE-777 to Email #1842 (untrusted). Follow the red path in the graph.");
  await wait(7000);

  // 4. Why it is unforgeable
  await caption(page, "The agent cannot fake where a value came from", "It never carries trust tags. The gate brokers every tool call, so it saw EVE-777 arrive in that email itself.");
  await wait(6500);

  // 5. Happy path with the real AI, then step-up
  await reset(page);
  await caption(page, "A legitimate payment, with a real AI agent (Gemini)", "MandateGate stays out of the way.");
  await page.getByRole("button", { name: /Legit payment/ }).click();
  await stamp(page, "ALLOWED").waitFor();
  await page.getByText("Vendor paid").first().waitFor();
  await wait(4000);

  await reset(page);
  await caption(page, "₹5,200 against a ₹5,000 approval", "Everything checks out except the amount, so MandateGate asks the human.");
  await page.getByRole("button", { name: /Over the limit/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor();
  await wait(4000);
  await caption(page, "You approve, and a pass is issued", "For exactly ₹5,200 to Acme's registered account. It works once, for 2 minutes.");
  await wait(2000);
  await dialog.getByRole("button", { name: /Approve/ }).click();
  await page.getByText("Vendor paid").first().waitFor();
  await wait(4000);

  // 6–7. Numbers and protocol attacks
  await page.getByRole("tab", { name: "Attack suite" }).click();
  await page.getByText("Attacks that got the attacker paid").waitFor();
  await caption(page, "Measured, not claimed: 21 attack cases, 113 runs", "Without MandateGate, 9 of 10 attacks paid the attacker. With it: 0. No legitimate payment was blocked.");
  await wait(7000);
  await page.getByText("Attacks on the token, the pass and the payment rail").scrollIntoViewIfNeeded();
  await wait(800);
  await caption(page, "Tampered, replayed, forged or skipped passes", "All rejected by the payment service, each for the right reason.");
  await wait(6000);
  await scrollTo(page, 0);
  const ai = page.getByRole("button", { name: /AI agent/ });
  if (await ai.count()) {
    await ai.click();
    await caption(page, "The real AI resisted every scam in our suite (0 of 54)", "That is good news, but luck you cannot build on. MandateGate's guarantee does not depend on it.");
    await wait(6500);
  }

  // 8. Close
  await page.getByRole("tab", { name: "Live demo" }).click();
  await caption(page, "The AI suggests. MandateGate decides.", "Logging in tells you which AI acted. MandateGate proves the human wanted this exact action.");
  await wait(5000);
} finally {
  await context.close(); // finalises the video file
  await browser.close();
}

const recorded = readdirSync(OUT).filter((f) => f.endsWith(".webm") && f !== "mandategate-demo.webm");
if (recorded.length !== 1) throw new Error(`expected one new recording in ${OUT}, found ${recorded.length}`);
rmSync(join(OUT, "mandategate-demo.webm"), { force: true });
renameSync(join(OUT, recorded[0]), join(OUT, "mandategate-demo.webm"));
console.log(`saved ${join(OUT, "mandategate-demo.webm")}`);

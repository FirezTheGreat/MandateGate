// The demo script (ROADMAP.md) as a test: run with `make dev` up, then `npm run e2e`.
// Screenshots land in e2e/screenshots/ for slides and the backup video.
import { expect, type Page, test } from "@playwright/test";

const shot = (page: Page, name: string) => page.screenshot({ path: `e2e/screenshots/${name}.png`, fullPage: true });

async function reset(page: Page) {
  await page.getByRole("button", { name: "Reset demo" }).click();
  await expect(page.getByText("Nothing yet: run a scenario")).toBeVisible();
}

async function protection(page: Page, on: boolean) {
  await page.getByRole("button", { name: on ? "With MandateGate" : "Without MandateGate", exact: true }).click();
  await expect(page.getByText(on ? "MandateGate on" : "MandateGate off", { exact: true })).toBeVisible();
}

const stamp = (page: Page, text: string) => page.getByRole("status").filter({ hasText: text });

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Live", { exact: true })).toBeVisible();
});

test("scam email without MandateGate: every check passes and the attacker is paid", async ({ page }) => {
  await reset(page);
  await protection(page, false);
  await page.getByRole("button", { name: /Scam email/ }).click();
  await expect(stamp(page, "ALLOWED")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("Attacker paid").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Simulated fooled agent").first()).toBeVisible();
  await shot(page, "1-baseline-attacker-paid");
});

test("scam email with MandateGate: blocked, traced to Email #1842", async ({ page }) => {
  await reset(page);
  await protection(page, true);
  await page.getByRole("button", { name: /Scam email/ }).click();
  await expect(stamp(page, "BLOCKED")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText("email:1842 (untrusted)").first()).toBeVisible();
  await expect(page.getByText("No money has moved")).toBeVisible();
  await page.waitForTimeout(1200); // let the graph settle into the final trace
  await shot(page, "2-gated-blocked");
});

test("over the limit with the real AI: MandateGate asks, you approve, exactly that amount is paid", async ({ page }) => {
  await reset(page);
  await protection(page, true);
  await page.getByRole("button", { name: /Over the limit/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible({ timeout: 120_000 });
  await shot(page, "3-step-up-ask-you-first");
  await dialog.getByRole("button", { name: /Approve/ }).click();
  await expect(page.getByText("Vendor paid").first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole("cell", { name: "₹5,200.00" })).toBeVisible();
  await shot(page, "4-step-up-approved-paid");
});

test("attack suite page shows the measured results", async ({ page }) => {
  await page.getByRole("tab", { name: "Attack suite" }).click();
  await expect(page.getByText("Attacks that got the attacker paid")).toBeVisible();
  await expect(page.getByText("Without MandateGate", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Attacker paid").first()).toBeVisible();
  await expect(page.getByText("Attacks on the token, the pass and the payment rail")).toBeVisible();
  await page.waitForTimeout(1000); // let the bars finish growing
  await shot(page, "6-attack-suite-simulated");
  const ai = page.getByRole("button", { name: /AI agent/ });
  if (await ai.count()) {
    await ai.click();
    await expect(page.getByText(/fooled \d\/3/).first()).toBeVisible();
    await page.waitForTimeout(1000);
    await shot(page, "7-attack-suite-ai");
  }
});

test("legit payment with the real AI goes through untouched", async ({ page }) => {
  await reset(page);
  await protection(page, true);
  await page.getByRole("button", { name: /Legit payment/ }).click();
  await expect(stamp(page, "ALLOWED")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("Vendor paid").first()).toBeVisible({ timeout: 60_000 });
  await shot(page, "5-legit-paid");
});

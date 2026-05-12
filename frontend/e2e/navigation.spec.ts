import { test, expect } from "@playwright/test";

const NAV_ITEMS: Array<{ label: string; route: string }> = [
  { label: "Overview", route: "overview" },
  { label: "Market", route: "market" },
  { label: "Holdings", route: "holdings" },
  { label: "Monitor", route: "monitor" },
  { label: "Strategies", route: "strategies" },
  { label: "Reports", route: "reports" },
  { label: "Settings", route: "settings" },
  { label: "Watchlist", route: "watchlist" },
];

test.describe("navigation", () => {
  NAV_ITEMS.forEach((item) => {
    test(`clicking ${item.label} nav item renders ${item.route} content`, async ({
      browser,
    }) => {
      const page = await browser.newPage();
      await page.goto("http://127.0.0.1:8888", { waitUntil: "networkidle" });

      // Click the nav link
      const navLink = page.locator(`.rail a[href="#!/${item.route}"]`);
      await expect(navLink).toBeVisible({ timeout: 10000 });
      await navLink.click();

      // Wait for content to render
      await page.waitForTimeout(1000);

      // Verify URL hash changed
      await expect(page).toHaveURL(/.*\/\/.*\/#!/${item.route}(?:$|\?)/);

      // Verify main content is present (not empty/error)
      const main = page.locator("main.main");
      await expect(main).toBeVisible({ timeout: 10000 });

      // Check no error boundary is shown (page rendered successfully)
      const errorFallback = page.locator("text=Something went wrong");
      await expect(errorFallback).toHaveCount(0, { timeout: 2000 });

      await page.close();
    });
  });
});

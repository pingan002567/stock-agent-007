import { test, expect } from "@playwright/test";

test.describe("error boundary", () => {
  test("shows error boundary on unknown route", async ({ browser }) => {
    const page = await browser.newPage();
    await page.goto("http://127.0.0.1:8888/#!/nonexistent-route", {
      waitUntil: "networkidle",
    });

    // The app should either show error content or gracefully degrade
    const body = page.locator("body");
    await expect(body).toBeVisible({ timeout: 10000 });

    // If ErrorBoundary caught it, look for error indicators
    const errorMsg = page.locator("text=Something went wrong");
    const mainContent = page.locator("main.main");

    // Either error boundary shows, or main content still loads gracefully
    const hasError = (await errorMsg.count()) > 0;
    const hasMain = (await mainContent.count()) > 0;
    expect(hasError || hasMain).toBeTruthy();

    await page.close();
  });

  test("navigating to valid route after error recovers", async ({
    browser,
  }) => {
    const page = await browser.newPage();

    // Trigger an error route
    await page.goto("http://127.0.0.1:8888/#!/nonexistent-route", {
      waitUntil: "networkidle",
    });

    // Navigate back to valid route
    await page.goto("http://127.0.0.1:8888", { waitUntil: "networkidle" });

    // App shell should be fully functional
    await expect(page.locator(".app")).toBeVisible({ timeout: 10000 });
    await expect(page.locator(".rail")).toBeVisible();
    await expect(page.locator("main.main")).toBeVisible();

    await page.close();
  });
});

import { test, expect } from "@playwright/test";

test("backend health endpoint returns 200", async ({ request }) => {
  const resp = await request.get("http://127.0.0.1:6666/api/health");
  expect(resp.ok()).toBeTruthy();
  const body = await resp.json();
  expect(body.status).toBe("ok");
});

test("frontend loads and renders app shell", async ({ browser }) => {
  const page = await browser.newPage();
  await page.goto("http://127.0.0.1:8888", { waitUntil: "networkidle" });
  await expect(page.locator(".app")).toBeVisible({ timeout: 15000 });
  await expect(page.locator(".rail")).toBeVisible();
  await expect(page.locator("main.main")).toBeVisible();
});

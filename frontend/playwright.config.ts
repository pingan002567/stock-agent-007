import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: "http://localhost:8888",
    headless: true,
  },
  webServer: [
    {
      command: "cd .. && bash scripts/dev.sh 2>&1",
      port: 8888,
      timeout: 120000,
      reuseExistingServer: true,
    },
  ],
});

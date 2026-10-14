import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:5173",
    browserName: "chromium",
    channel:
      process.env.PLAYWRIGHT_CHANNEL === "chromium"
        ? undefined
        : process.env.PLAYWRIGHT_CHANNEL || "msedge",
    headless: true,
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
  },
  outputDir: "../validation/ui/browser-results",
  webServer: {
    command: "node preview.mjs",
    url: "http://127.0.0.1:5173/dashboard",
    reuseExistingServer: true,
  },
});

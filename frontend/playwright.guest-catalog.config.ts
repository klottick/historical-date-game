import { defineConfig, devices } from "@playwright/test"

export default defineConfig({
  testDir: "./tests-guest-catalog",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir:
    "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/guest-browser-results",
  use: { baseURL: "http://localhost:5184", trace: "retain-on-failure" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "game-mobile", use: { ...devices["Pixel 5"] } },
    {
      name: "insecure-chromium",
      use: {
        ...devices["Desktop Chrome"],
        baseURL: "http://guest.test:5184",
        launchOptions: {
          args: ["--host-resolver-rules=MAP guest.test 127.0.0.1"],
        },
      },
    },
  ],
})

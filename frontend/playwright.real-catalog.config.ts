import { defineConfig, devices } from "@playwright/test"

export const realCatalogAPI = "http://localhost:8010/api/v1"
export const realCatalogAuthFile = "playwright/.auth/real-catalog.json"

// Servers are launched/ownership-checked explicitly; never reuse an arbitrary port.
export default defineConfig({
  testDir: "./tests-real-catalog",
  testMatch: "**/*.spec.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir:
    "../.superpowers/sdd/2026-10-12-historical-date-game-beta-followup/F2-evidence/browser-results",
  use: { baseURL: "http://localhost:5174", trace: "retain-on-failure" },
  projects: [
    { name: "setup", testMatch: /.*\.setup\.ts/ },
    ...[
      { name: "chromium", device: devices["Desktop Chrome"] },
      { name: "game-mobile", device: devices["Pixel 5"] },
    ].map(({ name, device }) => ({
      name,
      use: { ...device, storageState: realCatalogAuthFile },
      dependencies: ["setup"],
    })),
  ],
})

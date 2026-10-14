import { defineConfig, devices } from "@playwright/test"

export const realCatalogAPI = `${(process.env.REAL_CATALOG_API_ORIGIN || "http://localhost:8010").replace(/\/$/, "")}/api/v1`
export const realCatalogUIOrigin =
  process.env.REAL_CATALOG_UI_ORIGIN || "http://localhost:5174"
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
    "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/real-browser-results",
  use: { baseURL: realCatalogUIOrigin, trace: "retain-on-failure" },
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

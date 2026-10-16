import { defineConfig, devices } from "@playwright/test"
import { boardEvidence } from "./tests/utils/boardEvidence"

// Coordinator-only verification: never run account setup or reuse a live UI.
export default defineConfig({
  testDir: "./tests",
  testMatch: "game-session-bootstrap.spec.ts",
  timeout: 40_000,
  retries: 0,
  outputDir: `${boardEvidence}/bootstrap-browser-results`,
  use: { baseURL: "http://127.0.0.1:5194", serviceWorkers: "block" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command:
      "npx vite --config vite.bootstrap.config.ts --host 127.0.0.1 --port 5194 --strictPort",
    url: "http://127.0.0.1:5194/tests/fixtures/bootstrap.html",
    reuseExistingServer: false,
  },
})

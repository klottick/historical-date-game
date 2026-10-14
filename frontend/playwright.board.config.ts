import { defineConfig, devices } from "@playwright/test"

// Controlled DTO/native-DOM harness only: no account setup or backend consumer.
export default defineConfig({
  testDir: "./tests",
  testMatch: ["**/board-navigation.spec.ts", "**/board-ux.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  outputDir:
    "../.superpowers/sdd/2026-10-14-game-board-redesign/integration/board-browser-results",
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:5186",
  },
  webServer: {
    command:
      "node node_modules/vite/bin/vite.js --config vite.board.config.ts --mode board",
    url: "http://127.0.0.1:5186",
    reuseExistingServer: false,
  },
})

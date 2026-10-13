import { defineConfig, devices } from "@playwright/test"

// No account fixture, dotenv, backend, or private environment is needed here.
export default defineConfig({
  testDir: "./tests",
  testMatch: "game-identity-recovery.spec.ts",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: { baseURL: "http://127.0.0.1:5185", ...devices["Desktop Chrome"] },
  webServer: {
    command:
      "VITE_API_URL=http://127.0.0.1:5185 node node_modules/vite/bin/vite.js --config vite.identity.config.ts --host 127.0.0.1 --port 5185 --strictPort --mode identity",
    url: "http://127.0.0.1:5185",
    reuseExistingServer: false,
  },
})

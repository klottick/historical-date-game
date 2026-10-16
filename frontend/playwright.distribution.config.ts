import path from "node:path"
import { defineConfig, devices } from "@playwright/test"

const baseURL = process.env.DISTRIBUTION_BASE_URL
const evidence = process.env.DISTRIBUTION_EVIDENCE_DIR
if (!baseURL || !evidence)
  throw new Error("Set DISTRIBUTION_BASE_URL and DISTRIBUTION_EVIDENCE_DIR")

export default defineConfig({
  testDir: "./distribution",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  reporter: "list",
  outputDir: path.join(evidence, "results"),
  use: {
    ...devices["Desktop Chrome"],
    baseURL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1365, height: 900 } } },
    {
      name: "mobile",
      use: {
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
})

import { defineConfig, mergeConfig } from "vite"
import base from "./vite.config.ts"

// Browser-only Docker harness. Same-origin proxying preserves the real Lax,
// HttpOnly game cookie; never loosen the product's cookie policy for tests.
const target = process.env.PLAYWRIGHT_API_PROXY
if (!target) throw new Error("Explicit Playwright backend proxy required")

export default defineConfig(
  mergeConfig(base, {
    envDir: "./tests",
    define: { "import.meta.env.VITE_API_URL": JSON.stringify("") },
    server: { proxy: { "/api/": target, "/media/": target } },
  }),
)

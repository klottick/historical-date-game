import { defineConfig, mergeConfig } from "vite"
import base from "./vite.config.ts"

// Actual application/modules, but no private environment or shared optimizer cache.
export default defineConfig(
  mergeConfig(base, {
    envDir: "./tests",
    cacheDir:
      "../.superpowers/sdd/2026-10-14-game-board-redesign/integration/vite-board-cache",
    define: { "import.meta.env.VITE_API_URL": JSON.stringify("") },
    server: { host: "127.0.0.1", port: 5186, strictPort: true },
  }),
)

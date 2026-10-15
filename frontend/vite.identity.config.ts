import { defineConfig, mergeConfig } from "vite"
import base from "./vite.config.ts"

// Inherit the normal private-file denies, but load no private environment.
export default defineConfig(
  mergeConfig(base, {
    envDir: "./tests",
    cacheDir:
      "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/vite-identity-cache",
  }),
)

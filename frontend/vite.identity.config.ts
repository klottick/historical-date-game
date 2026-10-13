import { defineConfig, mergeConfig } from "vite"
import base from "./vite.config.ts"

// Inherit the normal private-file denies, but load no private environment.
export default defineConfig(mergeConfig(base, { envDir: "./tests" }))

import { defineConfig, loadConfigFromFile } from "vite"

// Only transform native modules; no router generation or application startup.
export default defineConfig(async (environment) => {
  const appConfig = await loadConfigFromFile(environment, "vite.config.ts")
  if (!appConfig)
    throw new Error("Application private-file protection is required")
  return {
    server: {
      ...appConfig.config.server,
      // Public module imports in the storage-denial sandbox need CORS. This
      // verification-only server has no API proxy; backend Origin rules stay intact.
      cors: { origin: ["http://127.0.0.1:5194", "null"] },
    },
    optimizeDeps: { entries: ["tests/fixtures/bootstrap.html"] },
  }
})

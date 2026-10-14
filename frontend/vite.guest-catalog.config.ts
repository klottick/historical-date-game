import { mergeConfig } from "vite"
import base from "./vite.config"

export default mergeConfig(base, {
  cacheDir:
    "../.superpowers/sdd/2026-10-13-historical-date-game-guest-play/task-5-evidence/vite-guest-cache",
  define: { "import.meta.env.VITE_API_URL": JSON.stringify("") },
  server: {
    host: "127.0.0.1",
    port: 5184,
    strictPort: true,
    allowedHosts: ["guest.test"],
    proxy: {
      "/api/": "http://127.0.0.1:8020",
      "/media/": "http://127.0.0.1:8020",
    },
  },
})

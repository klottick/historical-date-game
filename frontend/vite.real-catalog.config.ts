import { mergeConfig } from "vite"
import base from "./vite.config"

// Inherit the shared private-file boundary so alternate/fixture origins are safe.
export default mergeConfig(base, {
  // Use the visitor's origin even when the local .env points at a fixture API.
  // Root-relative media also stays on this origin via the proxy below.
  define: { "import.meta.env.VITE_API_URL": JSON.stringify("") },
  server: {
    host: "0.0.0.0",
    port: 5174,
    strictPort: true,
    proxy: {
      "/api/": "http://127.0.0.1:8010",
      "/media/": "http://127.0.0.1:8010",
    },
  },
})

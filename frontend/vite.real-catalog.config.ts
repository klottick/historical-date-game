import { mergeConfig } from "vite"
import base from "./vite.config"

// Inherit the shared private-file boundary so alternate/fixture origins are safe.
export default mergeConfig(base, {
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
  },
})

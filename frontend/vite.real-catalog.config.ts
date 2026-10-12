import { mergeConfig } from "vite"
import base from "./vite.config"

// Ignored files are not automatically private to Vite. Keep the fixture server
// configuration unchanged and deny local auth/test/catalog artifacts explicitly.
export default mergeConfig(base, {
  server: {
    host: "127.0.0.1",
    port: 5174,
    strictPort: true,
    fs: {
      strict: true,
      deny: [
        // Preserve Vite's default sensitive-file deny list when extending it.
        ".env",
        ".env.*",
        "*.{crt,pem,key,p12,pfx,cer,der}",
        ".npmrc",
        ".yarnrc.yml",
        "**/.git/**",
        "**/playwright/.auth/**",
        "**/tests-real-catalog/**",
        "**/.superpowers/**",
        "**/data/game/**",
      ],
    },
  },
})

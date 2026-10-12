import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import { tanstackRouter } from "@tanstack/router-plugin/vite"
import react from "@vitejs/plugin-react-swc"
import { defineConfig } from "vite"

// https://vitejs.dev/config/
export default defineConfig({
  // Every dev server shares this root, including the normal fixture launcher.
  // Ignored private files must not become HTTP assets through another origin.
  server: {
    fs: {
      strict: true,
      deny: [
        // Retain all installed Vite defaults when extending its deny list.
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
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  plugins: [
    tanstackRouter({
      target: "react",
      autoCodeSplitting: true,
    }),
    react(),
    tailwindcss(),
  ],
})

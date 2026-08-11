// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, nitro (build-only using cloudflare as a default target),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

// GitHub Pages build: `VITE_STATIC_DATA=1 BASE_PATH=/aflStats/ npm run build`
//   * nitro `static` preset prerenders to plain files (Pages runs no server)
//   * base path must match the repo name so asset URLs resolve under
//     https://<user>.github.io/<repo>/
const STATIC = process.env.VITE_STATIC_DATA === "1";
const BASE = process.env.BASE_PATH || "/";

export default defineConfig({
  tanstackStart: {
    // Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
    // nitro/vite builds from this
    server: { entry: "server" },
  },
  ...(STATIC
    ? {
        // Skip nitro entirely: Pages needs a plain client bundle, not a
        // server. TanStack Start renders as an SPA with a 404.html fallback.
        nitro: false as const,
        tanstackStart: { server: { entry: "server" }, spa: { enabled: true } },
        vite: { base: BASE },
      }
    : {}),
});

import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { paraglideVitePlugin } from "@inlang/paraglide-js";
import { defineConfig } from "vite";

const capacitorDebug =
  process.env.BUILD_TARGET === "capacitor" && process.env.CAP_DEBUG === "1";

export default defineConfig({
  plugins: [
    paraglideVitePlugin({
      project: "./project.inlang",
      outdir: "./src/lib/paraglide",
      strategy: ["localStorage", "cookie", "custom-browser", "baseLocale"],
    }),
    tailwindcss(),
    sveltekit(),
  ],
  build: {
    // The app as people get it is minified like the site. Readable code
    // and source maps — a third of the bundle — are for a build made to
    // be debugged on a device: CAP_DEBUG=1 pnpm build:app.
    ...(capacitorDebug ? { minify: false, sourcemap: true } : {}),
    rollupOptions: {
      output: {
        // A page asked for some 150 files, most of them under 4 KB (one
        // translated message each, one icon each): small chunks are
        // merged into their neighbours.
        experimentalMinChunkSize: 10_000,
      },
    },
  },
});

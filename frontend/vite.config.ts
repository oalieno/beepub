import adapterNode from "@sveltejs/adapter-node";
import adapterStatic from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";
import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { paraglideVitePlugin } from "@inlang/paraglide-js";
import { defineConfig } from "vite";

const capacitorDebug =
  process.env.BUILD_TARGET === "capacitor" && process.env.CAP_DEBUG === "1";
const isCapacitor = process.env.BUILD_TARGET === "capacitor";

export default defineConfig({
  plugins: [
    paraglideVitePlugin({
      project: "./project.inlang",
      outdir: "./src/lib/paraglide",
      strategy: ["localStorage", "cookie", "custom-browser", "baseLocale"],
    }),
    tailwindcss(),
    sveltekit({
      preprocess: vitePreprocess(),
      adapter: isCapacitor
        ? adapterStatic({ fallback: "index.html" })
        : adapterNode(),

      // Overridable so a second dev instance on the same working tree (the
      // e2e dev stack) doesn't fight the lab dev container over .svelte-kit.
      outDir: process.env.SVELTE_KIT_OUTDIR || ".svelte-kit",
    }),
  ],
  build: {
    // The app as people get it is minified like the site. Readable code
    // and source maps — a third of the bundle — are for a build made to
    // be debugged on a device: CAP_DEBUG=1 pnpm build:app.
    ...(capacitorDebug ? { minify: false, sourcemap: true } : {}),
    rolldownOptions: {
      output: {
        // Left alone, a page asks for well over a hundred files, most of
        // them a single translated message or a single icon. The ones
        // that more than one page uses are gathered into a chunk each;
        // one page's own stay with that page.
        codeSplitting: {
          groups: [
            {
              name: "messages",
              test: /paraglide[\\/]messages/,
              minShareCount: 2,
            },
            { name: "icons", test: /@lucide[\\/]svelte/, minShareCount: 2 },
          ],
        },
      },
    },
  },
});

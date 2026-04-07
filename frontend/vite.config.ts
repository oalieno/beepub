import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { paraglideVitePlugin } from "@inlang/paraglide-js";
import { defineConfig } from "vite";

const isCapacitor = process.env.BUILD_TARGET === "capacitor";

export default defineConfig({
  plugins: [
    paraglideVitePlugin({
      project: "./project.inlang",
      outdir: "./src/lib/paraglide",
      strategy: ["localStorage", "cookie", "baseLocale"],
    }),
    tailwindcss(),
    sveltekit(),
  ],
  resolve: {
    alias: {
      epubjs: new URL("./src/lib/epubjs/epub.js", import.meta.url).pathname,
    },
  },
  optimizeDeps: {
    include: ["epubjs"],
  },
  build: {
    // Disable minification for Capacitor debug builds
    ...(isCapacitor ? { minify: false, sourcemap: true } : {}),
  },
});

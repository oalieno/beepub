import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

const isCapacitor = process.env.BUILD_TARGET === "capacitor";

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
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

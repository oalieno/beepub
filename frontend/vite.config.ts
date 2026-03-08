import { sveltekit } from "@sveltejs/kit/vite";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

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
});

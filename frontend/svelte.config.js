import adapterNode from "@sveltejs/adapter-node";
import adapterStatic from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

const isCapacitor = process.env.BUILD_TARGET === "capacitor";

const config = {
  preprocess: vitePreprocess(),
  kit: {
    adapter: isCapacitor
      ? adapterStatic({ fallback: "index.html" })
      : adapterNode(),
    // Overridable so a second dev instance on the same working tree (the
    // e2e dev stack) doesn't fight the lab dev container over .svelte-kit.
    outDir: process.env.SVELTE_KIT_OUTDIR || ".svelte-kit",
  },
};
export default config;

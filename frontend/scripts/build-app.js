#!/usr/bin/env node
/**
 * Build script for Capacitor (static) target.
 *
 * adapter-static cannot coexist with +layout.server.ts at runtime because
 * SvelteKit's client router will try to fetch __data.json endpoints that
 * don't exist in the static output. We temporarily move the server layout
 * file out of the way during the build.
 */
import { execSync } from "node:child_process";
import { renameSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const SERVER_LAYOUT = resolve("src/routes/+layout.server.ts");
const SERVER_LAYOUT_BAK = resolve("src/routes/+layout.server.ts.bak");

function moveAside() {
  if (existsSync(SERVER_LAYOUT)) {
    renameSync(SERVER_LAYOUT, SERVER_LAYOUT_BAK);
  }
}

function restore() {
  if (existsSync(SERVER_LAYOUT_BAK)) {
    renameSync(SERVER_LAYOUT_BAK, SERVER_LAYOUT);
  }
}

moveAside();
try {
  execSync("BUILD_TARGET=capacitor VITE_CAPACITOR=true vite build", {
    stdio: "inherit",
    env: { ...process.env, BUILD_TARGET: "capacitor", VITE_CAPACITOR: "true" },
  });
} finally {
  restore();
}

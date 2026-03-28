// Build-time: use import.meta.env.VITE_CAPACITOR (only for ssr export in +layout.ts)
// Runtime: use isNative() everywhere else
export function isNative(): boolean {
  try {
    // @ts-expect-error Capacitor is only available in native builds
    return window.Capacitor?.isNativePlatform?.() ?? false;
  } catch {
    return false;
  }
}

export function isWeb(): boolean {
  return !isNative();
}

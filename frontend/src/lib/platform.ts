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

/** A curled page is turned by a finger: a device with no touch screen (a
 *  desktop) is not offered the curl, and one chosen elsewhere turns its
 *  own way there. */
export function canCurl(): boolean {
  return typeof navigator !== "undefined" && navigator.maxTouchPoints > 0;
}

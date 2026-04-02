/**
 * Svelte action that loads an image via fetch with auth headers in native mode.
 * In web mode, it sets the src directly (cookies handle auth).
 *
 * Usage: <img use:authedSrc={url} alt="..." />
 */
import { getAuthHeader } from "$lib/api/client";

function isNativeRuntime(): boolean {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return (window as any).Capacitor?.isNativePlatform?.() ?? false;
}

export function authedSrc(
  img: HTMLImageElement,
  src: string,
): { update: (src: string) => void; destroy: () => void } {
  let objectUrl: string | null = null;

  function cleanup() {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl);
      objectUrl = null;
    }
  }

  async function load(url: string) {
    cleanup();
    if (!url) return;

    if (!isNativeRuntime()) {
      img.src = url;
      return;
    }

    // Set a transparent 1x1 placeholder so the img has intrinsic size
    // and CSS layout (aspect-ratio, grid) works before the real image loads.
    if (!img.src) {
      img.src =
        "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
    }

    try {
      const res = await fetch(url, { headers: getAuthHeader() });
      if (!res.ok) return;
      const blob = await res.blob();
      objectUrl = URL.createObjectURL(blob);
      img.src = objectUrl;
    } catch {
      // Failed to load — leave img without src
    }
  }

  load(src);

  return {
    update(newSrc: string) {
      load(newSrc);
    },
    destroy() {
      cleanup();
    },
  };
}

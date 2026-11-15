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
  // The fetch in flight. A newer src (or the element going away) aborts
  // it, so an older answer can never land on top of a newer one and no
  // object URL is made for an image nobody will show.
  let pending: AbortController | null = null;

  // Decoding off the main thread: a page of covers must not hold up a
  // scroll or a tap.
  img.decoding = "async";

  function cleanup() {
    pending?.abort();
    pending = null;
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

    // A failure fires the element's own error event, as a plain src would
    // on the web, so an onerror fallback works the same on both.
    const mine = new AbortController();
    pending = mine;
    try {
      const res = await fetch(url, {
        headers: getAuthHeader(),
        signal: mine.signal,
      });
      if (!res.ok) {
        if (pending === mine) img.dispatchEvent(new Event("error"));
        return;
      }
      const blob = await res.blob();
      if (pending !== mine) return;
      pending = null;
      objectUrl = URL.createObjectURL(blob);
      img.src = objectUrl;
    } catch {
      if (pending === mine) img.dispatchEvent(new Event("error"));
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

/**
 * The same, for an image that is never put in the page (drawn to a
 * canvas, used as a texture): resolves once it has loaded, rejects when
 * it cannot be had. In the app it is fetched with the token — a bare
 * `new Image().src` there is refused by the server.
 */
export async function loadAuthedImage(url: string): Promise<HTMLImageElement> {
  let objectUrl: string | null = null;
  if (isNativeRuntime()) {
    const res = await fetch(url, { headers: getAuthHeader() });
    if (!res.ok) throw new Error(`image ${res.status}`);
    objectUrl = URL.createObjectURL(await res.blob());
  }
  const img = new Image();
  try {
    await new Promise<void>((loaded, failed) => {
      img.onload = () => loaded();
      img.onerror = () => failed(new Error("image failed to load"));
      img.src = objectUrl ?? url;
    });
  } finally {
    // Loaded, the image holds its own pixels.
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
  return img;
}

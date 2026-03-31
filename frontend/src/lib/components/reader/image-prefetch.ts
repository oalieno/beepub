/**
 * Image prefetching for adjacent epub sections.
 *
 * Preloads images from nearby sections so page turns feel instant,
 * especially for image-heavy books (manga, picture books).
 */

const PREFETCH_FORWARD = 3;
const PREFETCH_BACKWARD = 1;

const prefetchedUrls = new Set<string>();
let prefetchAbort: (() => void) | null = null;

function prefetchImage(url: string): Promise<void> {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve();
    img.onerror = () => resolve();
    img.src = url;
  });
}

/** Prefetch images from sections adjacent to the current one */
export function prefetchSections(epubBook: any, currentSectionIndex: number) {
  if (!epubBook?.spine) return;

  const currentSection = epubBook.spine.get(currentSectionIndex);
  if (!currentSection) return;

  prefetchAbort?.();

  const toPrefetch: any[] = [];

  let section: any = currentSection;
  for (let i = 0; i < PREFETCH_FORWARD; i++) {
    section = section.next?.();
    if (!section) break;
    toPrefetch.push(section);
  }

  section = currentSection;
  for (let i = 0; i < PREFETCH_BACKWARD; i++) {
    section = section.prev?.();
    if (!section) break;
    toPrefetch.push(section);
  }

  let cancelled = false;
  prefetchAbort = () => {
    cancelled = true;
  };

  (async () => {
    const allUrls: string[] = [];
    for (const s of toPrefetch) {
      try {
        const contents: any = await s.load(epubBook.load.bind(epubBook));
        contents.querySelectorAll("img").forEach((img: Element) => {
          const src = img.getAttribute("src");
          if (src) allUrls.push(new URL(src, s.url).href);
        });
        contents.querySelectorAll("image").forEach((img: Element) => {
          const href =
            img.getAttributeNS("http://www.w3.org/1999/xlink", "href") ||
            img.getAttribute("href") ||
            img.getAttribute("xlink:href");
          if (href) allUrls.push(new URL(href, s.url).href);
        });
      } catch {}
    }

    for (const url of allUrls) {
      if (cancelled) break;
      if (prefetchedUrls.has(url)) continue;
      prefetchedUrls.add(url);
      await prefetchImage(url);
    }
  })();
}

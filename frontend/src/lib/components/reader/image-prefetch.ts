/**
 * Image prefetching for adjacent epub sections.
 *
 * Two modes:
 * - Native/auth: triggers resources._fetchImage() to create blob URLs.
 *   substituteAsync() finds them already resolved → instant page turns.
 * - Web: uses new Image() to warm the browser cache (cookie auth works).
 */

const PREFETCH_FORWARD = 3;
const PREFETCH_BACKWARD = 1;

const prefetchedSections = new Set<number>();
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

  const resources = epubBook.resources;
  const useResourcesFetch = resources?._imageIndices?.size > 0;

  (async () => {
    for (const s of toPrefetch) {
      if (cancelled) break;
      if (prefetchedSections.has(s.index)) continue;
      prefetchedSections.add(s.index);

      try {
        const contents: any = await s.load(epubBook.load.bind(epubBook));

        if (useResourcesFetch) {
          // Native/auth mode: trigger blob URL creation via resources
          const serializer = new XMLSerializer();
          const html = serializer.serializeToString(contents);
          resources.urls.forEach((href: string, i: number) => {
            if (cancelled) return;
            if (resources.replacementUrls[i]) return;
            if (!resources._imageIndices.has(i)) return;
            if (href && html.indexOf(href) !== -1) {
              resources._fetchImage(i);
            }
          });
        } else {
          // Web mode: warm browser cache with new Image()
          const allUrls: string[] = [];
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
          for (const url of allUrls) {
            if (cancelled) break;
            if (prefetchedUrls.has(url)) continue;
            prefetchedUrls.add(url);
            await prefetchImage(url);
          }
        }
      } catch {
        // Section load failed, skip
      }
    }
  })();
}

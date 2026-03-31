/**
 * Table of contents utilities for the epub reader.
 */

type TocEntry = { label: string; href: string; subitems?: TocEntry[] };

export function getSpineIndexForHref(
  epubBook: any,
  tocHref: string,
): number {
  const base = tocHref.split("#")[0];
  const item = epubBook?.spine?.get(base);
  return item?.index ?? -1;
}

/**
 * Find the active TOC href for a given spine section index.
 * Flattens the TOC, sorts by spine position, and picks the last entry
 * whose spine index <= the current section. For same-file entries with
 * fragment anchors, refines by checking element positions in the DOM.
 */
export function findActiveTocHref(
  epubBook: any,
  rendition: any,
  tocData: TocEntry[],
  sectionIndex: number,
): string {
  if (!epubBook || tocData.length === 0) return "";

  const flat: { href: string; spineIndex: number }[] = [];
  for (const item of tocData) {
    const si = getSpineIndexForHref(epubBook, item.href);
    if (si !== -1) flat.push({ href: item.href, spineIndex: si });
    if (item.subitems) {
      for (const sub of item.subitems) {
        const ssi = getSpineIndexForHref(epubBook, sub.href);
        if (ssi !== -1) flat.push({ href: sub.href, spineIndex: ssi });
      }
    }
  }

  flat.sort((a, b) => a.spineIndex - b.spineIndex);

  let active = "";
  for (const entry of flat) {
    if (entry.spineIndex <= sectionIndex) {
      active = entry.href;
    } else {
      break;
    }
  }

  // Refine: for entries sharing the same spine file, check fragment positions
  if (active && rendition) {
    const sameFile = flat.filter(
      (e) =>
        e.spineIndex === getSpineIndexForHref(epubBook, active) &&
        e.spineIndex === sectionIndex,
    );

    if (sameFile.length > 1) {
      const contents = rendition.getContents();
      if (contents && contents.length > 0) {
        const doc = contents[0]?.document;
        if (doc) {
          let refined = sameFile[0].href;
          for (const entry of sameFile) {
            const fragment = entry.href.split("#")[1];
            if (!fragment) {
              refined = entry.href;
              continue;
            }
            const el = doc.getElementById(fragment);
            if (el) {
              const rect = el.getBoundingClientRect();
              if (rect.top <= 10) {
                refined = entry.href;
              }
            }
          }
          active = refined;
        }
      }
    }
  }

  return active;
}

/**
 * OPDS 1.2 (Atom) feed parsing — pure XML-to-model, no Capacitor imports.
 *
 * Built against our own catalog (backend/app/routers/opds.py) but tolerant
 * of real-world variance: entries are classified per entry, never by feed
 * Content-Type (feeds can mix navigation and books); namespace lookups
 * prefer the proper namespace but fall back to localName for sloppy
 * servers; hrefs may be relative; and pagination follows the feed-level
 * rel="next" link verbatim — query parameter conventions differ per
 * server, so the URL is opaque.
 *
 * Resolved URLs are filtered to https: here, which is where the app's
 * HTTPS-only posture (no ATS exceptions on iOS) gets enforced.
 */

const ATOM_NS = "http://www.w3.org/2005/Atom";
const DC_TERMS_NS = "http://purl.org/dc/terms/";

// Acquisition rels form a family (…/acquisition, …/acquisition/open-access,
// /borrow, …) — matched by prefix. Image rels include the older OPDS 1.0
// cover/thumbnail spellings still seen in the wild.
const ACQUISITION_REL_PREFIX = "http://opds-spec.org/acquisition";
const IMAGE_RELS = ["http://opds-spec.org/image", "http://opds-spec.org/cover"];
const THUMBNAIL_RELS = [
  "http://opds-spec.org/image/thumbnail",
  "http://opds-spec.org/thumbnail",
];

// Entry links with these rels never mean "browse into this feed"; anything
// else with an Atom type does (subsection, sort/new, alternate, no rel, …).
const STRUCTURAL_RELS = new Set([
  "self",
  "start",
  "up",
  "next",
  "previous",
  "first",
  "last",
  "search",
  "related",
]);

export interface OpdsFeed {
  title: string;
  entries: OpdsEntry[];
  /** Absolute URL of the next page, when the feed is paginated. */
  nextUrl?: string;
  /** Absolute URL of the OpenSearch description document, when offered. */
  searchDescUrl?: string;
}

export type OpdsEntry = OpdsNavEntry | OpdsBookEntry;

export interface OpdsNavEntry {
  kind: "nav";
  key: string;
  title: string;
  href: string;
  content?: string;
}

export interface OpdsBookEntry {
  kind: "book";
  key: string;
  title: string;
  authors: string[];
  summary?: string;
  language?: string;
  coverUrl?: string;
  thumbnailUrl?: string;
  /** Undefined when no EPUB acquisition link exists — shown as unavailable. */
  epubUrl?: string;
  updated?: string;
}

export class OpdsParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OpdsParseError";
  }
}

interface OpdsLink {
  rel: string;
  type: string;
  href: string;
}

/** First matching child, preferring the given namespace but accepting any
 *  namespace with the right localName (sloppy servers omit or mangle it). */
function childByName(
  el: Element,
  ns: string,
  localName: string,
): Element | null {
  let fallback: Element | null = null;
  for (const child of Array.from(el.children)) {
    if (child.localName !== localName) continue;
    if (child.namespaceURI === ns) return child;
    fallback ??= child;
  }
  return fallback;
}

/** All matching children — the namespaced set when non-empty, else every
 *  child with the right localName. */
function childrenByName(el: Element, ns: string, localName: string): Element[] {
  const all = Array.from(el.children).filter((c) => c.localName === localName);
  const inNs = all.filter((c) => c.namespaceURI === ns);
  return inNs.length > 0 ? inNs : all;
}

function childText(el: Element, ns: string, localName: string): string | null {
  const text = childByName(el, ns, localName)?.textContent?.trim();
  return text ? text : null;
}

function resolveHttpsUrl(href: string | null, baseUrl: string): string | null {
  if (!href) return null;
  try {
    const url = new URL(href, baseUrl);
    return url.protocol === "https:" ? url.toString() : null;
  } catch {
    return null;
  }
}

function readLinks(el: Element, baseUrl: string): OpdsLink[] {
  const links: OpdsLink[] = [];
  for (const link of childrenByName(el, ATOM_NS, "link")) {
    const href = resolveHttpsUrl(link.getAttribute("href"), baseUrl);
    if (!href) continue;
    links.push({
      rel: link.getAttribute("rel") ?? "",
      type: link.getAttribute("type") ?? "",
      href,
    });
  }
  return links;
}

function parseEntry(
  el: Element,
  feedUrl: string,
  index: number,
): OpdsEntry | null {
  const title = childText(el, ATOM_NS, "title") ?? "";
  const links = readLinks(el, feedUrl);
  const acquisition = links.filter((l) =>
    l.rel.startsWith(ACQUISITION_REL_PREFIX),
  );

  if (acquisition.length > 0) {
    const id = childText(el, ATOM_NS, "id");
    const epubUrl = acquisition.find((l) =>
      l.type.includes("application/epub+zip"),
    )?.href;
    const authors = childrenByName(el, ATOM_NS, "author")
      .map((a) => childText(a, ATOM_NS, "name"))
      .filter((n): n is string => n !== null);
    return {
      kind: "book",
      // Stable identity for {#each} keying and download state even when the
      // server omits atom ids.
      key: id ?? epubUrl ?? acquisition[0].href,
      title: title || `Untitled #${index + 1}`,
      authors,
      summary:
        childText(el, ATOM_NS, "summary") ??
        childText(el, ATOM_NS, "content") ??
        undefined,
      language: childText(el, DC_TERMS_NS, "language") ?? undefined,
      coverUrl: links.find((l) => IMAGE_RELS.includes(l.rel))?.href,
      thumbnailUrl: links.find((l) => THUMBNAIL_RELS.includes(l.rel))?.href,
      epubUrl,
      updated: childText(el, ATOM_NS, "updated") ?? undefined,
    };
  }

  const nav = links.find(
    (l) => l.type.includes("atom+xml") && !STRUCTURAL_RELS.has(l.rel),
  );
  if (!nav) return null; // Neither a book nor a browsable feed — skip.
  return {
    kind: "nav",
    key: childText(el, ATOM_NS, "id") ?? nav.href,
    title: title || nav.href,
    href: nav.href,
    content:
      childText(el, ATOM_NS, "content") ??
      childText(el, ATOM_NS, "summary") ??
      undefined,
  };
}

export function parseOpdsFeed(xml: string, feedUrl: string): OpdsFeed {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  // WebKit reports malformed XML via a parsererror element in the XHTML
  // namespace — a plain getElementsByTagName misses it.
  if (doc.getElementsByTagNameNS("*", "parsererror").length > 0) {
    throw new OpdsParseError("Malformed XML");
  }
  const feed = doc.documentElement;
  if (!feed || feed.localName !== "feed") {
    throw new OpdsParseError(
      `Not an Atom feed (root <${feed?.localName ?? "?"}>)`,
    );
  }

  const feedLinks = readLinks(feed, feedUrl);
  const entries: OpdsEntry[] = [];
  childrenByName(feed, ATOM_NS, "entry").forEach((el, index) => {
    const entry = parseEntry(el, feedUrl, index);
    if (entry) entries.push(entry);
  });

  return {
    title: childText(feed, ATOM_NS, "title") ?? "",
    entries,
    nextUrl: feedLinks.find((l) => l.rel === "next")?.href,
    searchDescUrl: feedLinks.find(
      (l) => l.rel === "search" && l.type.includes("opensearchdescription"),
    )?.href,
  };
}

// {searchTerms} must survive resolution against the document URL — the URL
// constructor would percent-encode the braces — so it travels through as an
// alphanumeric token and is restored afterwards.
const TERMS_TOKEN = "OPDSSEARCHTERMS0";

/**
 * Extract the search URL template from an OpenSearch description document.
 * Returns an absolute https template still containing `{searchTerms}`, or
 * null when the document offers no usable Atom search target.
 */
export function parseOpenSearchDescription(
  xml: string,
  docUrl: string,
): string | null {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  if (doc.getElementsByTagNameNS("*", "parsererror").length > 0) return null;
  const candidates = Array.from(doc.getElementsByTagNameNS("*", "Url"))
    .map((u) => ({
      type: u.getAttribute("type") ?? "",
      template: u.getAttribute("template") ?? "",
    }))
    .filter(
      (u) =>
        u.template.includes("{searchTerms}") &&
        (u.type.includes("atom") || u.type.includes("profile=opds-catalog")),
    );
  const pick =
    candidates.find((u) => u.type.includes("profile=opds-catalog")) ??
    candidates[0];
  if (!pick) return null;
  // Optional OpenSearch parameters ({startPage?} and friends) default empty.
  const raw = pick.template.replace(/\{[^}]*\?\}/g, "");
  try {
    const resolved = new URL(
      raw.replaceAll("{searchTerms}", TERMS_TOKEN),
      docUrl,
    ).toString();
    if (!resolved.startsWith("https:")) return null;
    return resolved.replaceAll(TERMS_TOKEN, "{searchTerms}");
  } catch {
    return null;
  }
}

export function buildSearchUrl(template: string, terms: string): string {
  return template.replaceAll("{searchTerms}", encodeURIComponent(terms));
}

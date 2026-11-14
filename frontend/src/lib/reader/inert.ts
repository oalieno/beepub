/**
 * A book's documents are made inert before they are shown.
 *
 * A chapter is rendered in a frame that shares the app's origin (the
 * reader measures and decorates it from outside), so a script in a book
 * — in a `<script>`, an `onerror`, a `javascript:` link — would run as
 * the reader who opened it: it could call any API with their session.
 * Books are files from anywhere; none of them is given that.
 *
 * Each HTML document gets a Content-Security-Policy of its own, as the
 * first thing in its head, before the browser has parsed anything else:
 * no script of any kind runs, no plugin loads. Nothing is taken out of
 * the document, so the positions that highlights and progress are kept
 * by (CFIs count elements) stay what they were. Only where a policy has
 * nowhere to go — a document without a head, an SVG shown as a page —
 * are the scripts and handlers themselves removed.
 */

const HTML_TYPES = ["application/xhtml+xml", "text/html"];
const SVG_TYPE = "image/svg+xml";
const SCRIPT_TYPES = /(java|ecma)script/i;
const XHTML_NS = "http://www.w3.org/1999/xhtml";

export const INERT_POLICY = "script-src 'none'; object-src 'none'";

function strip(doc: Document) {
  for (const el of Array.from(doc.querySelectorAll("script"))) el.remove();
  for (const el of Array.from(doc.querySelectorAll("*")))
    for (const attr of Array.from(el.attributes)) {
      if (/^on/i.test(attr.localName)) el.removeAttributeNode(attr);
      else if (
        /^(href|src|action|formaction)$/i.test(attr.localName) &&
        /^\s*javascript:/i.test(attr.value)
      )
        el.removeAttributeNode(attr);
    }
}

/** One of the book's files, as text of the given type, made inert.
 *  What is not a document comes back as it is — except a script, which
 *  comes back empty. */
export function inert(text: string, type: string): string {
  if (SCRIPT_TYPES.test(type)) return "";
  const html = HTML_TYPES.includes(type);
  if (!html && type !== SVG_TYPE) return text;
  const doc = new DOMParser().parseFromString(
    text,
    type as DOMParserSupportedType,
  );
  if (doc.querySelector("parsererror")) return text;
  const head = html
    ? Array.from(doc.documentElement.children).find(
        (el) => el.localName === "head",
      )
    : undefined;
  if (head) {
    const meta = doc.createElementNS(XHTML_NS, "meta");
    meta.setAttribute("http-equiv", "Content-Security-Policy");
    meta.setAttribute("content", INERT_POLICY);
    head.insertBefore(meta, head.firstChild);
  } else {
    strip(doc);
  }
  return type === "text/html"
    ? `<!DOCTYPE html>${doc.documentElement.outerHTML}`
    : new XMLSerializer().serializeToString(doc);
}

interface TransformDetail {
  data: string | Blob | Promise<string | Blob>;
  type: string | Promise<string>;
}

const guarded = (type: string) =>
  SCRIPT_TYPES.test(type) || HTML_TYPES.includes(type) || type === SVG_TYPE;

/** Every file the book hands to the page passes through `inert`. */
export function keepInert(transformTarget: EventTarget | undefined) {
  transformTarget?.addEventListener("data", (event) => {
    const detail = (event as CustomEvent<TransformDetail>).detail;
    const data = detail.data;
    detail.data = Promise.resolve(detail.type).then(async (type) => {
      const file = await data;
      if (!guarded(type)) return file;
      // (A document that refers back to itself arrives unread, as a blob.)
      return inert(typeof file === "string" ? file : await file.text(), type);
    });
  });
}

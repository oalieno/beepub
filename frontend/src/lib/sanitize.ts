import DOMPurify from "dompurify";

// Allow common inline + block tags used by epub metadata, markdown notes,
// and footnote content. Drops <script>, <style>, <iframe>, event handlers,
// and javascript: URLs by default.
const ALLOWED_TAGS = [
  "a",
  "b",
  "blockquote",
  "br",
  "code",
  "del",
  "div",
  "em",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "hr",
  "i",
  "img",
  "ins",
  "li",
  "ol",
  "p",
  "pre",
  "q",
  "s",
  "small",
  "span",
  "strong",
  "sub",
  "sup",
  "table",
  "tbody",
  "td",
  "tfoot",
  "th",
  "thead",
  "tr",
  "u",
  "ul",
];

const ALLOWED_ATTR = [
  "href",
  "title",
  "alt",
  "src",
  "class",
  "id",
  "lang",
  "dir",
];

export function sanitizeHtml(html: string | null | undefined): string {
  if (!html) return "";
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
  });
}

function escapeText(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// Book descriptions come in two shapes: HTML from EPUB metadata, and
// plain text from the metadata plugins (paragraphs separated by blank
// lines). Rendering plain text as HTML collapses its newlines into
// spaces, so paragraph structure has to be rebuilt first.
export function sanitizeDescription(text: string | null | undefined): string {
  if (!text) return "";
  if (/<[a-z][^>]*>/i.test(text)) return sanitizeHtml(text);
  const html = text
    .split(/\n{2,}/)
    .map(
      (paragraph) => `<p>${escapeText(paragraph).replace(/\n/g, "<br>")}</p>`,
    )
    .join("");
  return sanitizeHtml(html);
}

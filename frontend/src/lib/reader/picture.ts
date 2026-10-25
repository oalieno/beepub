/**
 * The library's image-book rule, shared by the local import and the image
 * pager's routing; the server's twin is backend/app/services/epub_text.py.
 * A picture page is a page whose body says nothing: nothing is left once
 * whitespace, digits, punctuation and symbols are gone (a manga page's
 * `<ploc>12</ploc>`, a "- 12 -" footer, a bare <img> wrapper). An image
 * book is one whose linear spine items are at least 80% picture pages: a
 * manga keeps its TOC, credits and colophon as text.
 */

const NOT_TEXT = /[\s\p{Nd}\p{P}\p{S}]/gu;

export function isPictureText(text: string): boolean {
  return text.replace(NOT_TEXT, "") === "";
}

export function isImageBookShare(linear: number, pictures: number): boolean {
  return linear > 0 && pictures * 5 >= linear * 4;
}

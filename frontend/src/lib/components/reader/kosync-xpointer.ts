/**
 * Resolve a crengine/KOReader xpointer (as pushed through kosync) into a
 * position inside an epub.js section document.
 *
 * Device positions look like `/body/DocFragment[12]/body/p[35]/text().260`:
 * DocFragment[N] is the 1-based spine item, the rest is an element path
 * (1-based per-tag child indexing), optionally ending in a text-node step
 * and a character offset. Walking that path through our own DOM gives a
 * paragraph-level jump target — far better than the chapter start, which is
 * all the percentage can offer once renderer pagination scales diverge.
 *
 * crengine's DOM is not ours (it strips whitespace-only text nodes and can
 * normalize markup), so resolution is best-effort: any step that doesn't
 * match aborts, and the caller degrades to the chapter-start jump.
 */

interface ElementStep {
  kind: "element";
  tag: string;
  index: number;
}

interface TextStep {
  kind: "text";
  index: number;
}

export interface ParsedXpointer {
  /** 0-based spine index (DocFragment[N] → N-1). */
  sectionIndex: number;
  steps: (ElementStep | TextStep)[];
  charOffset: number | null;
}

const DOC_FRAGMENT_RE = /^\/body\/DocFragment\[(\d+)\]/;

export function parseKosyncXpointer(xpointer: string): ParsedXpointer | null {
  const frag = DOC_FRAGMENT_RE.exec(xpointer);
  if (!frag) return null;
  const n = parseInt(frag[1], 10);
  if (!Number.isFinite(n) || n < 1) return null;

  let rest = xpointer.slice(frag[0].length);
  // Trailing ".260" character offset, appended after the last step.
  let charOffset: number | null = null;
  const offsetMatch = /\.(\d+)$/.exec(rest);
  if (offsetMatch) {
    charOffset = parseInt(offsetMatch[1], 10);
    rest = rest.slice(0, -offsetMatch[0].length);
  }

  const steps: (ElementStep | TextStep)[] = [];
  for (const raw of rest.split("/")) {
    if (!raw) continue;
    const m = /^(text\(\)|[A-Za-z][\w:-]*)(?:\[(\d+)\])?$/.exec(raw);
    if (!m) return null;
    const index = m[2] ? parseInt(m[2], 10) : 1;
    if (index < 1) return null;
    if (m[1] === "text()") steps.push({ kind: "text", index });
    else steps.push({ kind: "element", tag: m[1].toLowerCase(), index });
  }
  if (!steps.length) return null;
  return { sectionIndex: n - 1, steps, charOffset };
}

/**
 * Walk the parsed path through a section document. The path starts at the
 * fragment root, so the first step (`body`) matches among the children of
 * `documentElement`. Returns a collapsed Range at the target, or null when
 * any step fails to match.
 */
export function resolveXpointerRange(
  doc: Document,
  parsed: ParsedXpointer,
): Range | null {
  let el: Element | null = doc.documentElement;
  let textNode: Text | null = null;
  for (const step of parsed.steps) {
    if (!el || textNode) return null; // a text() step must be terminal
    if (step.kind === "element") {
      const matches: Element[] = Array.from(el.children).filter(
        (c) => c.localName.toLowerCase() === step.tag,
      );
      el = matches[step.index - 1] ?? null;
    } else {
      // crengine's DOM has no whitespace-only text nodes between blocks —
      // skip them when counting or the index drifts against ours.
      const texts = Array.from(el.childNodes).filter(
        (node): node is Text =>
          node.nodeType === 3 &&
          !!node.nodeValue &&
          node.nodeValue.trim() !== "",
      );
      textNode = texts[step.index - 1] ?? null;
      if (!textNode) return null;
    }
  }

  const range = doc.createRange();
  if (textNode) {
    // Whitespace normalization differs between engines; clamping keeps a
    // slightly-off offset inside the right text node (paragraph accuracy
    // is the goal, not character accuracy).
    const offset = Math.min(
      parsed.charOffset ?? 0,
      textNode.nodeValue?.length ?? 0,
    );
    range.setStart(textNode, offset);
  } else if (el) {
    // Element-terminated path (offset, if any, was crengine-internal).
    range.setStart(el, 0);
  } else {
    return null;
  }
  range.collapse(true);
  return range;
}

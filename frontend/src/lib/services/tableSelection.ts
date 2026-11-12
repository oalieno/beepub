/**
 * Selection in the library table, Finder-style: a click picks one row,
 * ⌘/Ctrl+click adds or drops one, Shift+click takes the run from the
 * anchor to the row in the order the list shows. `focus` is the book the
 * side panel shows and the one the list opens on when its order changes.
 */

export interface TableSelection {
  selected: Set<string>;
  anchor: string | null;
  focus: string | null;
}

export const NO_SELECTION: TableSelection = {
  selected: new Set(),
  anchor: null,
  focus: null,
};

export function only(id: string): TableSelection {
  return { selected: new Set([id]), anchor: id, focus: id };
}

export function applyClick(
  state: TableSelection,
  id: string,
  mods: { shift: boolean; toggle: boolean },
  order: string[],
): TableSelection {
  if (mods.shift && state.anchor) {
    const from = order.indexOf(state.anchor);
    const to = order.indexOf(id);
    if (from >= 0 && to >= 0) {
      const [lo, hi] = from < to ? [from, to] : [to, from];
      return {
        selected: new Set(order.slice(lo, hi + 1)),
        anchor: state.anchor,
        focus: id,
      };
    }
  }
  if (mods.toggle) {
    const selected = new Set(state.selected);
    if (selected.has(id)) {
      selected.delete(id);
      const last = [...selected].at(-1) ?? null;
      return { selected, anchor: last, focus: last };
    }
    selected.add(id);
    return { selected, anchor: id, focus: id };
  }
  return only(id);
}

const FULL_WIDTH_DIGIT = /[０-９]/g;
// A closing note in brackets, as in 「4（完）」 or 「3 [番外]」.
const TRAILING_NOTE = /\s*[(（[【〔][^)）\]】〕\d]*[)）\]】〕]\s*$/;
// The number a title ends on, before a volume word or a closing bracket if
// there is one: 「星海旅人 3」「星海旅人 第3卷」「星海旅人(3)」「v2.5」.
const TRAILING_NUMBER =
  /(\d+(?:\.\d+)?)\s*[卷集冊册部話话巻篇]?\s*[)）\]】〕]?\s*$/;

/** The volume number a title ends on, or null. */
export function volumeFromTitle(title: string): number | null {
  const text = title
    .replace(FULL_WIDTH_DIGIT, (d) =>
      String.fromCharCode(d.charCodeAt(0) - 0xfee0),
    )
    .replace(TRAILING_NOTE, "");
  const match = text.match(TRAILING_NUMBER);
  return match ? Number(match[1]) : null;
}

export type Numbering = "title" | "order" | "keep";

/** Each book's number under the series being set: from its title, by its
 *  place in the list, or null for "keep the number it shows". */
export function seriesNumbers(
  titles: string[],
  numbering: Numbering,
): (number | null)[] {
  if (numbering === "order") return titles.map((_, i) => i + 1);
  if (numbering === "title") return titles.map(volumeFromTitle);
  return titles.map(() => null);
}

/**
 * CFIs written by other readers, rewritten into the shape the vendored
 * foliate parser reads. Applied where foreign CFIs enter (core.resolve,
 * collapseCFI); CFIs we generate never need it.
 */

/** Top-level comma positions (outside `[...]` assertions, not `^`-escaped). */
function topLevelCommas(body: string): number[] {
  const at: number[] = [];
  let depth = 0;
  for (let i = 0; i < body.length; i++) {
    const ch = body[i];
    if (ch === "^") i++;
    else if (ch === "[") depth++;
    else if (ch === "]") depth = Math.max(0, depth - 1);
    else if (ch === "," && depth === 0) at.push(i);
  }
  return at;
}

// The last step of a path: `/N` plus an optional `[...]` assertion.
const LAST_STEP = /\/\d+(?:\[(?:\^.|[^\]])*\])?$/;

/**
 * Apple Books (and some other readers) keep a range's text-node step in
 * the shared parent path and write the endpoints as bare offsets:
 *   epubcfi(/6/4!/4/8/1,:4,:17)
 * Both are valid CFIs for the same range, but foliate's parser needs every
 * endpoint to start with a step — it throws on `:4`. Move the parent's
 * last step into both endpoints:
 *   epubcfi(/6/4!/4/8,/1:4,/1:17)
 */
export function normalizeCFI(cfi: string): string {
  const match = /^epubcfi\((.*)\)$/.exec(cfi);
  if (!match) return cfi;
  const body = match[1];
  const commas = topLevelCommas(body);
  if (commas.length !== 2) return cfi;
  const parent = body.slice(0, commas[0]);
  const start = body.slice(commas[0] + 1, commas[1]);
  const end = body.slice(commas[1] + 1);
  if (!start.startsWith(":") || !end.startsWith(":")) return cfi;
  const step = LAST_STEP.exec(parent);
  if (!step) return cfi;
  const head = parent.slice(0, step.index);
  if (!head || head.endsWith("!")) return cfi;
  return `epubcfi(${head},${step[0]}${start},${step[0]}${end})`;
}

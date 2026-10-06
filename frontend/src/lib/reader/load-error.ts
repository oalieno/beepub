/**
 * A destination's section could not be put on screen: its load failed
 * (network error, a status that is not an answer, a stalled request), or
 * the reader chose another destination before it arrived (`abandoned`).
 * Either way the reader is where it was.
 *
 * Kept apart from core.ts so that code outside the browser-only engine
 * can tell this error from any other without importing the engine.
 */
export class SectionLoadError extends Error {
  constructor(
    public readonly index: number,
    public readonly abandoned = false,
  ) {
    super(
      abandoned
        ? `The way to section ${index} was abandoned`
        : `Section ${index} could not be loaded`,
    );
    this.name = "SectionLoadError";
  }
}

export function isSectionLoadError(e: unknown): e is SectionLoadError {
  return (
    !!e && typeof e === "object" && (e as Error).name === "SectionLoadError"
  );
}

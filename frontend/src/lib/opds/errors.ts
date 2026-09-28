/** blocked: the server refused the address (outside the catalog, or on
 *  the private network while the admin blocks that). */
export type OpdsErrorKind = "auth" | "http" | "network" | "parse" | "blocked";

/** Typed transport/parse failure; the UI translates by `kind`. */
export class OpdsError extends Error {
  constructor(
    public readonly kind: OpdsErrorKind,
    public readonly status?: number,
    cause?: unknown,
  ) {
    super(`OPDS ${kind} error${status ? ` (${status})` : ""}`, { cause });
    this.name = "OpdsError";
  }
}

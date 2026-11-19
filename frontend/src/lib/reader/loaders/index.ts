/**
 * Loader selection: a BookSource payload says whether the book streams
 * from the server or arrived as one file; the reader gets a BookLoader
 * either way and never learns which.
 */
import type { BookPayload } from "#lib/reading/source.ts";

import { makeServerLoader } from "./serverLibrary";
import type { BookLoader } from "./types";

export type { BookLoader } from "./types";
export { LoaderHttpError, makeServerLoader } from "./serverLibrary";

export async function loaderFromPayload(
  payload: BookPayload,
): Promise<BookLoader> {
  if (payload.kind === "bytes") {
    // The zip code loads only when a whole-file book actually opens.
    const { makeLocalLoader } = await import("./local");
    return makeLocalLoader(payload.data);
  }
  return makeServerLoader(payload.url, payload.authHeader);
}

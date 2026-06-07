import { get, put } from "./client";
import type { SeriesOut } from "$lib/types";

export const seriesApi = {
  // Explicitly-rated series (across all libraries) — for the tier page.
  listRated: () => get("/series/rated") as Promise<SeriesOut[]>,

  // Series identity is (library_id, series_key). libraryId pins which one; omit
  // it for an old/shared ?name= link and the backend resolves the first match.
  get: (seriesName: string, libraryId?: string) =>
    get(
      `/series/detail?name=${encodeURIComponent(seriesName)}${
        libraryId ? `&library=${libraryId}` : ""
      }`,
    ) as Promise<SeriesOut>,

  // null rating clears the explicit series rating
  updateRating: (
    seriesName: string,
    libraryId: string,
    rating: number | null,
  ) =>
    put("/series/rating", {
      series_name: seriesName,
      library_id: libraryId,
      rating,
    }),

  updateNotes: (seriesName: string, libraryId: string, notes: string | null) =>
    put("/series/notes", {
      series_name: seriesName,
      library_id: libraryId,
      notes,
    }),
};

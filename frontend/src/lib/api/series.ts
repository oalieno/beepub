import { get, put } from "./client";
import type { SeriesOut } from "$lib/types";

export const seriesApi = {
  // Explicitly-rated series (across all libraries) — for the tier page.
  listRated: () => get("/series/rated") as Promise<SeriesOut[]>,

  get: (seriesName: string) =>
    get(
      `/series/detail?name=${encodeURIComponent(seriesName)}`,
    ) as Promise<SeriesOut>,

  // null rating clears the explicit series rating
  updateRating: (seriesName: string, rating: number | null) =>
    put("/series/rating", { series_name: seriesName, rating }),

  updateNotes: (seriesName: string, notes: string | null) =>
    put("/series/notes", { series_name: seriesName, notes }),
};

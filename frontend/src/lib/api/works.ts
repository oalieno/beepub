import { get, post, patch, del } from "./client";
import type { DuplicateSuggestionsOut, WorkOut } from "$lib/types";

export const worksApi = {
  create: (bookIds: string[]) =>
    post("/works", { book_ids: bookIds }) as Promise<WorkOut>,

  getSuggestions: () =>
    get("/works/suggestions") as Promise<DuplicateSuggestionsOut>,

  getWork: (workId: string) => get(`/works/${workId}`) as Promise<WorkOut>,

  update: (
    workId: string,
    data: { title?: string; authors?: string[]; primary_book_id?: string },
  ) => patch(`/works/${workId}`, data) as Promise<WorkOut>,

  deleteWork: (workId: string) => del(`/works/${workId}`) as Promise<void>,

  addBook: (workId: string, bookId: string) =>
    post(`/works/${workId}/books/${bookId}`) as Promise<WorkOut>,

  removeBook: (workId: string, bookId: string) =>
    del(`/works/${workId}/books/${bookId}`) as Promise<void>,

  exclude: (bookIds: string[]) =>
    post("/works/exclusions", { book_ids: bookIds }) as Promise<{
      status: string;
      pairs: number;
    }>,
};

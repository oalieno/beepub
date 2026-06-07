import { get, post, put, del } from "./client";
import type { BookshelfOut, LibraryFeedItem } from "$lib/types";

export const bookshelvesApi = {
  list: () => get("/bookshelves") as Promise<BookshelfOut[]>,

  get: (id: string) => get(`/bookshelves/${id}`) as Promise<BookshelfOut>,

  create: (data: { name: string; description?: string }) =>
    post("/bookshelves", data) as Promise<BookshelfOut>,

  update: (id: string, data: { name?: string; description?: string }) =>
    put(`/bookshelves/${id}`, data) as Promise<BookshelfOut>,

  delete: (id: string) => del(`/bookshelves/${id}`),

  // Shelf contents in sort order — books and whole series, mixed.
  getItems: (id: string) =>
    get(`/bookshelves/${id}/items`) as Promise<LibraryFeedItem[]>,

  addBook: (id: string, bookId: string) =>
    post(`/bookshelves/${id}/books`, { book_id: bookId }),

  removeBook: (id: string, bookId: string) =>
    del(`/bookshelves/${id}/books/${bookId}`),

  addSeries: (id: string, seriesName: string, libraryId: string) =>
    post(`/bookshelves/${id}/series`, {
      series_name: seriesName,
      library_id: libraryId,
    }),

  removeSeries: (id: string, seriesKey: string, libraryId: string) =>
    del(
      `/bookshelves/${id}/series?key=${encodeURIComponent(seriesKey)}&library=${libraryId}`,
    ),

  reorder: (id: string, bookIds: string[]) =>
    put(`/bookshelves/${id}/books/reorder`, { book_ids: bookIds }),
};

export const aiApi = {
  getStatus: () => get("/ai/status") as Promise<import("$lib/types").AiStatus>,
};

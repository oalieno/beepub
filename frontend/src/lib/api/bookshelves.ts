import { get, post, put, del } from "./client";
import type { BookshelfOut, BookOut } from "$lib/types";

export const bookshelvesApi = {
  list: () => get("/bookshelves") as Promise<BookshelfOut[]>,

  get: (id: string) => get(`/bookshelves/${id}`) as Promise<BookshelfOut>,

  create: (data: { name: string; description?: string; is_public?: boolean }) =>
    post("/bookshelves", data) as Promise<BookshelfOut>,

  update: (
    id: string,
    data: { name?: string; description?: string; is_public?: boolean },
  ) => put(`/bookshelves/${id}`, data) as Promise<BookshelfOut>,

  delete: (id: string) => del(`/bookshelves/${id}`),

  getBooks: (id: string) =>
    get(`/bookshelves/${id}/books`) as Promise<BookOut[]>,

  addBook: (id: string, bookId: string) =>
    post(`/bookshelves/${id}/books`, { book_id: bookId }),

  removeBook: (id: string, bookId: string) =>
    del(`/bookshelves/${id}/books/${bookId}`),

  reorder: (id: string, bookIds: string[]) =>
    put(`/bookshelves/${id}/books/reorder`, { book_ids: bookIds }),
};

export const aiApi = {
  getStatus: () => get("/ai/status") as Promise<import("$lib/types").AiStatus>,
};

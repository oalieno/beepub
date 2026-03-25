import { get, post, put, del } from "./client";
import type { LibraryOut, PaginatedBooks } from "$lib/types";

export interface LibraryMemberOut {
  user_id: string;
  granted_by: string;
  granted_at: string;
}

export const librariesApi = {
  list: () => get("/libraries") as Promise<LibraryOut[]>,

  get: (id: string) => get(`/libraries/${id}`) as Promise<LibraryOut>,

  create: (data: { name: string; description?: string; visibility?: string }) =>
    post("/libraries", data) as Promise<LibraryOut>,

  update: (
    id: string,
    data: { name?: string; description?: string; visibility?: string },
  ) => put(`/libraries/${id}`, data) as Promise<LibraryOut>,

  delete: (id: string) => del(`/libraries/${id}`),

  getBooks: (
    id: string,
    options?: {
      search?: string;
      author?: string;
      tag?: string;
      series?: string;
      sort?: string;
      order?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    if (options?.search) params.set("search", options.search);
    if (options?.author) params.set("author", options.author);
    if (options?.tag) params.set("tag", options.tag);
    if (options?.series) params.set("series", options.series);
    if (options?.sort) params.set("sort", options.sort);
    if (options?.order) params.set("order", options.order);
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.offset != null) params.set("offset", String(options.offset));
    const qs = params.toString();
    return get(
      `/libraries/${id}/books${qs ? `?${qs}` : ""}`,
    ) as Promise<PaginatedBooks>;
  },

  getMembers: (id: string) =>
    get(`/libraries/${id}/members`) as Promise<LibraryMemberOut[]>,

  addMember: (id: string, userId: string) =>
    post(`/libraries/${id}/members`, { user_id: userId }),

  removeMember: (id: string, userId: string) =>
    del(`/libraries/${id}/members/${userId}`),

  addBook: (id: string, bookId: string) =>
    post(`/libraries/${id}/books`, { book_id: bookId }),

  removeBook: (id: string, bookId: string) =>
    del(`/libraries/${id}/books/${bookId}`),
};

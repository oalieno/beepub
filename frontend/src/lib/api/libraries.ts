import { get, post, put, del } from "./client";
import type { LibraryOut, PaginatedBooks } from "$lib/types";

export interface LibraryMemberOut {
  user_id: string;
  granted_by: string;
  granted_at: string;
}

export const librariesApi = {
  list: (token: string) => get("/libraries", token) as Promise<LibraryOut[]>,

  get: (id: string, token: string) =>
    get(`/libraries/${id}`, token) as Promise<LibraryOut>,

  create: (
    data: { name: string; description?: string; visibility?: string },
    token: string,
  ) => post("/libraries", data, token) as Promise<LibraryOut>,

  update: (
    id: string,
    data: { name?: string; description?: string; visibility?: string },
    token: string,
  ) => put(`/libraries/${id}`, data, token) as Promise<LibraryOut>,

  delete: (id: string, token: string) => del(`/libraries/${id}`, token),

  getBooks: (
    id: string,
    token: string,
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
      token,
    ) as Promise<PaginatedBooks>;
  },

  getMembers: (id: string, token: string) =>
    get(`/libraries/${id}/members`, token) as Promise<LibraryMemberOut[]>,

  addMember: (id: string, userId: string, token: string) =>
    post(`/libraries/${id}/members`, { user_id: userId }, token),

  removeMember: (id: string, userId: string, token: string) =>
    del(`/libraries/${id}/members/${userId}`, token),

  addBook: (id: string, bookId: string, token: string) =>
    post(`/libraries/${id}/books`, { book_id: bookId }, token),

  removeBook: (id: string, bookId: string, token: string) =>
    del(`/libraries/${id}/books/${bookId}`, token),
};

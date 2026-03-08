import { get, post, put, del } from "./client";
import type { LibraryOut, BookOut } from "$lib/types";

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

  getBooks: (id: string, token: string, search?: string, sort?: string) => {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (sort) params.set("sort", sort);
    const qs = params.toString();
    return get(`/libraries/${id}/books${qs ? `?${qs}` : ""}`, token) as Promise<
      BookOut[]
    >;
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

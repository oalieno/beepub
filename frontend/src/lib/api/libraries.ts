import { get, post, put, del } from "./client";
import type { LibraryOut } from "$lib/types";

export const librariesApi = {
  list: () => get("/libraries") as Promise<LibraryOut[]>,

  get: (id: string) => get(`/libraries/${id}`) as Promise<LibraryOut>,

  create: (data: { name: string; description?: string }) =>
    post("/libraries", data) as Promise<LibraryOut>,

  update: (id: string, data: { name?: string; description?: string }) =>
    put(`/libraries/${id}`, data) as Promise<LibraryOut>,

  delete: (id: string) => del(`/libraries/${id}`),
};

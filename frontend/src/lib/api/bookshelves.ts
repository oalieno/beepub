import { get, post, put, del } from "./client";
import type { BookshelfOut, BookOut } from "$lib/types";

export const bookshelvesApi = {
  list: (token: string) =>
    get("/bookshelves", token) as Promise<BookshelfOut[]>,

  get: (id: string, token: string) =>
    get(`/bookshelves/${id}`, token) as Promise<BookshelfOut>,

  create: (
    data: { name: string; description?: string; is_public?: boolean },
    token: string,
  ) => post("/bookshelves", data, token) as Promise<BookshelfOut>,

  update: (
    id: string,
    data: { name?: string; description?: string; is_public?: boolean },
    token: string,
  ) => put(`/bookshelves/${id}`, data, token) as Promise<BookshelfOut>,

  delete: (id: string, token: string) => del(`/bookshelves/${id}`, token),

  getBooks: (id: string, token: string) =>
    get(`/bookshelves/${id}/books`, token) as Promise<BookOut[]>,

  addBook: (id: string, bookId: string, token: string) =>
    post(`/bookshelves/${id}/books`, { book_id: bookId }, token),

  removeBook: (id: string, bookId: string, token: string) =>
    del(`/bookshelves/${id}/books/${bookId}`, token),

  reorder: (id: string, bookIds: string[], token: string) =>
    put(`/bookshelves/${id}/books/reorder`, { book_ids: bookIds }, token),
};

export const adminApi = {
  getUsers: (token: string) =>
    get("/admin/users", token) as Promise<import("$lib/types").UserOut[]>,

  updateRole: (userId: string, role: string, token: string) =>
    put(`/admin/users/${userId}/role`, { role }, token),

  deleteUser: (userId: string, token: string) =>
    del(`/admin/users/${userId}`, token),

  getStats: (token: string) =>
    get("/admin/stats", token) as Promise<import("$lib/types").AdminStats>,

  // Calibre integration
  getCalibreLibraries: (token: string) =>
    get("/admin/calibre/libraries", token) as Promise<
      import("$lib/types").CalibreLibraryInfo[]
    >,

  linkCalibreLibrary: (
    data: { calibre_path: string; name?: string },
    token: string,
  ) =>
    post("/admin/calibre/libraries", data, token) as Promise<{
      library_id: string;
    }>,

  syncCalibreLibrary: (libraryId: string, token: string) =>
    post(`/admin/calibre/libraries/${libraryId}/sync`, {}, token),

  getCalibreLibraryStatus: (libraryId: string, token: string) =>
    get(`/admin/calibre/libraries/${libraryId}/status`, token) as Promise<
      import("$lib/types").CalibreLibraryStatus
    >,

  // App Settings
  getSettings: (token: string) =>
    get("/admin/settings", token) as Promise<
      import("$lib/types").AdminSettings
    >,

  updateSettings: (
    data: Partial<import("$lib/types").AdminSettings>,
    token: string,
  ) =>
    put("/admin/settings", data, token) as Promise<
      import("$lib/types").AdminSettings
    >,
};

export const aiApi = {
  getStatus: (token: string) =>
    get("/ai/status", token) as Promise<import("$lib/types").AiStatus>,
};

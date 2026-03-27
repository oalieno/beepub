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

export const adminApi = {
  getUsers: () =>
    get("/admin/users") as Promise<import("$lib/types").UserOut[]>,

  updateRole: (userId: string, role: string) =>
    put(`/admin/users/${userId}/role`, { role }),

  deleteUser: (userId: string) => del(`/admin/users/${userId}`),

  getStats: () =>
    get("/admin/stats") as Promise<import("$lib/types").AdminStats>,

  // Calibre integration
  getCalibreLibraries: () =>
    get("/admin/calibre/libraries") as Promise<
      import("$lib/types").CalibreLibraryInfo[]
    >,

  linkCalibreLibrary: (data: { calibre_path: string; name?: string }) =>
    post("/admin/calibre/libraries", data) as Promise<{
      library_id: string;
    }>,

  syncCalibreLibrary: (libraryId: string) =>
    post(`/admin/calibre/libraries/${libraryId}/sync`, {}),

  getCalibreLibraryStatus: (libraryId: string) =>
    get(`/admin/calibre/libraries/${libraryId}/status`) as Promise<
      import("$lib/types").CalibreLibraryStatus
    >,

  // App Settings
  getSettings: () =>
    get("/admin/settings") as Promise<import("$lib/types").AdminSettings>,

  updateSettings: (data: Partial<import("$lib/types").AdminSettings>) =>
    put("/admin/settings", data) as Promise<import("$lib/types").AdminSettings>,

  getAiModels: (provider: string) =>
    get(`/admin/ai/models?provider=${provider}`) as Promise<
      { id: string; name: string }[]
    >,

  buildSearchIndex: () =>
    post("/search/build-index") as Promise<{
      status: string;
      message: string;
    }>,

  // Job Queue
  getJobs: () =>
    get("/admin/jobs") as Promise<import("$lib/types").AllJobsResponse>,

  triggerJob: (jobType: string) =>
    post(`/admin/jobs/${jobType}`, {}) as Promise<{
      status: string;
      job_type: string;
    }>,

  stopJob: (jobType: string) =>
    del(`/admin/jobs/${jobType}`) as Promise<{
      status: string;
      job_type: string;
    }>,

  // LLM Usage
  getLlmUsage: (period: string = "month", feature?: string) => {
    const params = new URLSearchParams({ period });
    if (feature) params.set("feature", feature);
    return get(`/admin/llm-usage?${params}`) as Promise<
      import("$lib/types").LlmUsageResponse
    >;
  },

  // Book Reports
  getReports: (resolved: boolean = false) =>
    get(`/admin/reports?resolved=${resolved}`) as Promise<
      import("$lib/types").BookReport[]
    >,

  resolveReport: (reportId: string) =>
    put(`/admin/reports/${reportId}/resolve`, {}),
};

export const aiApi = {
  getStatus: () => get("/ai/status") as Promise<import("$lib/types").AiStatus>,
};

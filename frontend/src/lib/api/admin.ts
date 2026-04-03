import { get, post, put, del } from "./client";
import type { UserOut, UserLibraryAccess } from "$lib/types";

export const adminApi = {
  // Users
  getUsers: () => get("/admin/users") as Promise<UserOut[]>,

  getUser: (userId: string) =>
    get(`/admin/users/${userId}`) as Promise<UserOut>,

  createUser: (data: { username: string; password: string }) =>
    post("/admin/users", data) as Promise<UserOut>,

  updateRole: (userId: string, role: string) =>
    put(`/admin/users/${userId}/role`, { role }),

  resetPassword: (userId: string, newPassword: string) =>
    put(`/admin/users/${userId}/password`, { new_password: newPassword }),

  deleteUser: (userId: string) => del(`/admin/users/${userId}`),

  updatePermissions: (userId: string, data: { can_download: boolean }) =>
    put(`/admin/users/${userId}/permissions`, data) as Promise<UserOut>,

  getLibraryAccess: (userId: string) =>
    get(`/admin/users/${userId}/library-access`) as Promise<
      UserLibraryAccess[]
    >,

  updateLibraryAccess: (userId: string, excludedLibraryIds: string[]) =>
    put(`/admin/users/${userId}/library-access`, {
      excluded_library_ids: excludedLibraryIds,
    }),

  // Stats
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

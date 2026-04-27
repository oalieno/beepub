import { get, post, put, patch, del, apiBase, getAuthHeader } from "./client";
import type {
  BookOut,
  BookReport,
  BookWithInteractionOut,
  CompanionConversationOut,
  CompanionConversationSummary,
  EpubImageInfo,
  ExternalMetadataOut,
  HighlightOut,
  IllustrationOut,
  InteractionOut,
  PaginatedBooks,
  PaginatedBooksWithInteraction,
  ProgressOut,
  ReadingStats,
  ReadingStatus,
  ReferenceImageInput,
  SeriesNeighborsOut,
  StylePromptOut,
  TagBrowseSection,
} from "$lib/types";

export const booksApi = {
  upload: (file: File, libraryId?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (libraryId) formData.append("library_id", libraryId);
    return fetch(`${apiBase()}/books`, {
      method: "POST",
      headers: getAuthHeader(),
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return res.json() as Promise<BookOut>;
    });
  },

  get: (bookId: string) => get(`/books/${bookId}`) as Promise<BookOut>,

  getSeriesNeighbors: (bookId: string) =>
    get(`/books/${bookId}/series-neighbors`) as Promise<SeriesNeighborsOut>,

  updateMetadata: (
    bookId: string,
    data: {
      title?: string | null;
      authors?: string[] | null;
      publisher?: string | null;
      description?: string | null;
      published_date?: string | null;
      series?: string | null;
      series_index?: number | null;
      tags?: string[] | null;
    },
  ) => put(`/books/${bookId}/metadata`, data) as Promise<BookOut>,

  delete: (bookId: string) => del(`/books/${bookId}`),

  getFileUrl: (bookId: string) => `${apiBase()}/books/${bookId}/file`,

  getCoverUrl: (bookId: string) => `${apiBase()}/books/${bookId}/cover`,

  refreshMetadata: (bookId: string) => post(`/books/${bookId}/refresh`),

  getExternal: (bookId: string) =>
    get(`/books/${bookId}/external`) as Promise<ExternalMetadataOut[]>,

  unlinkExternal: (bookId: string, source: string) =>
    del(`/books/${bookId}/external/${source}`),

  updateExternalUrl: (
    bookId: string,
    source: string,
    sourceUrl: string | null,
  ) =>
    put(`/books/${bookId}/external/${source}/url`, {
      source_url: sourceUrl,
    }) as Promise<ExternalMetadataOut>,

  getEditions: (bookId: string) =>
    get(`/books/${bookId}/editions`) as Promise<
      Array<{
        id: string;
        display_title: string | null;
        display_authors: string[] | null;
        cover_path: string | null;
        epub_isbn: string | null;
        metadata_count: number;
        created_at: string;
      }>
    >,

  getInteraction: (bookId: string) =>
    get(`/books/${bookId}/interaction`) as Promise<InteractionOut>,

  updateRating: (bookId: string, rating: number | null) =>
    put(`/books/${bookId}/rating`, { rating }),

  updateFavorite: (bookId: string, isFavorite: boolean) =>
    put(`/books/${bookId}/favorite`, { is_favorite: isFavorite }),

  updateReadingStatus: (
    bookId: string,
    data: {
      reading_status: ReadingStatus | null;
      started_at?: string | null;
      finished_at?: string | null;
    },
  ) => put(`/books/${bookId}/reading-status`, data),

  updateNotes: (bookId: string, notes: string | null) =>
    put(`/books/${bookId}/notes`, { notes }),

  getProgress: (bookId: string) =>
    get(`/books/${bookId}/progress`) as Promise<ProgressOut>,

  updateProgress: (
    bookId: string,
    data: {
      cfi: string;
      percentage: number;
      current_page?: number;
      font_size?: number;
      section_index?: number;
      section_page?: number;
      section_page_counts?: number[];
      total_pages?: number;
      track_activity?: boolean;
    },
  ) => put(`/books/${bookId}/progress`, data),

  getHighlights: (bookId: string) =>
    get(`/books/${bookId}/highlights`) as Promise<HighlightOut[]>,

  createHighlight: (
    bookId: string,
    data: { cfi_range: string; text: string; color: string; note?: string },
  ) => post(`/books/${bookId}/highlights`, data) as Promise<HighlightOut>,

  updateHighlight: (
    bookId: string,
    highlightId: string,
    data: { color?: string; note?: string },
  ) =>
    put(
      `/books/${bookId}/highlights/${highlightId}`,
      data,
    ) as Promise<HighlightOut>,

  deleteHighlight: (bookId: string, highlightId: string) =>
    del(`/books/${bookId}/highlights/${highlightId}`),

  getAllHighlights: () => get("/highlights") as Promise<HighlightOut[]>,

  // Illustrations
  getIllustrations: (bookId: string) =>
    get(`/books/${bookId}/illustrations`) as Promise<IllustrationOut[]>,

  createIllustration: (
    bookId: string,
    data: {
      cfi_range: string;
      text: string;
      style_prompt?: string;
      custom_prompt?: string;
      reference_images?: ReferenceImageInput[];
    },
  ) => post(`/books/${bookId}/illustrations`, data) as Promise<IllustrationOut>,

  getIllustration: (bookId: string, illustrationId: string) =>
    get(
      `/books/${bookId}/illustrations/${illustrationId}`,
    ) as Promise<IllustrationOut>,

  deleteIllustration: (bookId: string, illustrationId: string) =>
    del(`/books/${bookId}/illustrations/${illustrationId}`),

  getStylePrompts: (bookId: string) =>
    get(`/books/${bookId}/illustrations/styles`) as Promise<StylePromptOut[]>,

  getIllustrationImageUrl: (bookId: string, illustrationId: string) =>
    `${apiBase()}/books/${bookId}/illustrations/${illustrationId}/image`,

  getEpubImages: (bookId: string) =>
    get(`/books/${bookId}/images`) as Promise<EpubImageInfo[]>,

  getBatchInteractions: (bookIds: string[]) =>
    post("/books/interactions/batch", { book_ids: bookIds }) as Promise<{
      interactions: Record<string, { reading_status: string | null }>;
    }>,

  search: (query: string, limit: number = 20) => {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return get(`/books/search?${params}`) as Promise<{
      items: (BookOut & { library_name: string | null })[];
      total: number;
    }>;
  },

  getMyBooks: (options?: {
    status?: ReadingStatus;
    favorite?: boolean;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) => {
    const params = new URLSearchParams();
    if (options?.status) params.set("status", options.status);
    if (options?.favorite !== undefined)
      params.set("favorite", String(options.favorite));
    if (options?.sort) params.set("sort", options.sort);
    if (options?.order) params.set("order", options.order);
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.offset) params.set("offset", String(options.offset));
    const qs = params.toString();
    return get(
      `/books/me${qs ? `?${qs}` : ""}`,
    ) as Promise<PaginatedBooksWithInteraction>;
  },

  getReadingActivity: (year: number) =>
    get(`/books/reading-activity?year=${year}`) as Promise<
      { date: string; seconds: number }[]
    >,

  getRandomBooks: (count: number = 8) =>
    get(`/books/random?count=${count}`) as Promise<BookOut[]>,

  getSimilar: (bookId: string, limit: number = 10) =>
    get(`/books/${bookId}/similar?limit=${limit}`) as Promise<BookOut[]>,

  retag: (bookId: string) => post(`/books/${bookId}/retag`),

  getRecommendations: (limit: number = 30) =>
    get(`/books/discover/recommendations?limit=${limit}`) as Promise<
      BookWithInteractionOut[]
    >,

  getBrowseByCategory: (category: string) =>
    get(`/books/discover/browse?category=${category}`) as Promise<
      TagBrowseSection[]
    >,

  getAll: (options?: {
    search?: string;
    author?: string;
    tag?: string;
    series?: string;
    sort?: string;
    order?: string;
    limit?: number;
    offset?: number;
  }) => {
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
    return get(`/books/all${qs ? `?${qs}` : ""}`) as Promise<PaginatedBooks>;
  },

  // Companion
  listCompanionConversations: (bookId: string) =>
    get(`/books/${bookId}/companion`) as Promise<
      CompanionConversationSummary[]
    >,

  getCompanionConversation: (bookId: string, conversationId: string) =>
    get(
      `/books/${bookId}/companion/${conversationId}`,
    ) as Promise<CompanionConversationOut>,

  sendCompanionMessage: (
    bookId: string,
    data: {
      message: string;
      selected_text?: string | null;
      cfi_range?: string | null;
      current_cfi?: string | null;
      conversation_id?: string | null;
    },
  ) =>
    fetch(`${apiBase()}/books/${bookId}/companion`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify(data),
    }),

  renameCompanionConversation: (
    bookId: string,
    conversationId: string,
    title: string,
  ) => patch(`/books/${bookId}/companion/${conversationId}`, { title }),

  deleteCompanionConversation: (bookId: string, conversationId: string) =>
    del(`/books/${bookId}/companion/${conversationId}`),

  getReadingStats: () => get("/books/reading-stats") as Promise<ReadingStats>,

  updateReadingGoal: (goalSeconds: number | null) =>
    put("/books/reading-goal", {
      goal_seconds: goalSeconds,
    }) as Promise<ReadingStats>,

  reportIssue: (
    bookId: string,
    data: { issue_type: string; description?: string },
  ) => post(`/books/${bookId}/reports`, data) as Promise<BookReport>,

  getReports: (bookId: string) =>
    get(`/books/${bookId}/reports`) as Promise<BookReport[]>,
};

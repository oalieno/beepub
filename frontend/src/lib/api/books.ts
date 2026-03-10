import { get, post, put, del } from "./client";
import type {
  BookOut,
  BookWithInteractionOut,
  ExternalMetadataOut,
  HighlightOut,
  IllustrationOut,
  InteractionOut,
  PaginatedBooksWithInteraction,
  ProgressOut,
  ReadingStatus,
  StylePromptOut,
} from "$lib/types";

export const booksApi = {
  upload: (file: File, token: string, libraryId?: string) => {
    const formData = new FormData();
    formData.append("file", file);
    if (libraryId) formData.append("library_id", libraryId);
    return fetch("/api/books", {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = (await res.json().catch(() => ({}))) as { detail?: string };
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return res.json() as Promise<BookOut>;
    });
  },

  get: (bookId: string, token: string) =>
    get(`/books/${bookId}`, token) as Promise<BookOut>,

  updateMetadata: (
    bookId: string,
    data: {
      title?: string | null;
      authors?: string[] | null;
      publisher?: string | null;
      description?: string | null;
      published_date?: string | null;
    },
    token: string,
  ) => put(`/books/${bookId}/metadata`, data, token) as Promise<BookOut>,

  delete: (bookId: string, token: string) => del(`/books/${bookId}`, token),

  getFileUrl: (bookId: string) => `/api/books/${bookId}/file`,

  getCoverUrl: (bookId: string) => `/api/books/${bookId}/cover`,

  refreshMetadata: (bookId: string, token: string) =>
    post(`/books/${bookId}/refresh`, undefined, token),

  getExternal: (bookId: string, token: string) =>
    get(`/books/${bookId}/external`, token) as Promise<ExternalMetadataOut[]>,

  getInteraction: (bookId: string, token: string) =>
    get(`/books/${bookId}/interaction`, token) as Promise<InteractionOut>,

  updateRating: (bookId: string, rating: number | null, token: string) =>
    put(`/books/${bookId}/rating`, { rating }, token),

  updateFavorite: (bookId: string, isFavorite: boolean, token: string) =>
    put(`/books/${bookId}/favorite`, { is_favorite: isFavorite }, token),

  updateReadingStatus: (
    bookId: string,
    data: {
      reading_status: ReadingStatus | null;
      started_at?: string | null;
      finished_at?: string | null;
    },
    token: string,
  ) => put(`/books/${bookId}/reading-status`, data, token),

  updateNotes: (bookId: string, notes: string | null, token: string) =>
    put(`/books/${bookId}/notes`, { notes }, token),

  getProgress: (bookId: string, token: string) =>
    get(`/books/${bookId}/progress`, token) as Promise<ProgressOut>,

  updateProgress: (
    bookId: string,
    data: {
      cfi: string;
      percentage: number;
      font_size?: number;
      section_index?: number;
      section_page?: number;
    },
    token: string,
  ) => put(`/books/${bookId}/progress`, data, token),

  getHighlights: (bookId: string, token: string) =>
    get(`/books/${bookId}/highlights`, token) as Promise<HighlightOut[]>,

  createHighlight: (
    bookId: string,
    data: { cfi_range: string; text: string; color: string; note?: string },
    token: string,
  ) =>
    post(`/books/${bookId}/highlights`, data, token) as Promise<HighlightOut>,

  updateHighlight: (
    bookId: string,
    highlightId: string,
    data: { color?: string; note?: string },
    token: string,
  ) =>
    put(
      `/books/${bookId}/highlights/${highlightId}`,
      data,
      token,
    ) as Promise<HighlightOut>,

  deleteHighlight: (bookId: string, highlightId: string, token: string) =>
    del(`/books/${bookId}/highlights/${highlightId}`, token),

  getAllHighlights: (token: string) =>
    get("/highlights", token) as Promise<HighlightOut[]>,

  // Illustrations
  getIllustrations: (bookId: string, token: string) =>
    get(`/books/${bookId}/illustrations`, token) as Promise<IllustrationOut[]>,

  createIllustration: (
    bookId: string,
    data: {
      cfi_range: string;
      text: string;
      style_prompt?: string;
      custom_prompt?: string;
    },
    token: string,
  ) =>
    post(
      `/books/${bookId}/illustrations`,
      data,
      token,
    ) as Promise<IllustrationOut>,

  getIllustration: (bookId: string, illustrationId: string, token: string) =>
    get(
      `/books/${bookId}/illustrations/${illustrationId}`,
      token,
    ) as Promise<IllustrationOut>,

  deleteIllustration: (bookId: string, illustrationId: string, token: string) =>
    del(`/books/${bookId}/illustrations/${illustrationId}`, token),

  getStylePrompts: (bookId: string, token: string) =>
    get(`/books/${bookId}/illustrations/styles`, token) as Promise<
      StylePromptOut[]
    >,

  getIllustrationImageUrl: (bookId: string, illustrationId: string) =>
    `/api/books/${bookId}/illustrations/${illustrationId}/image`,

  getMyBooks: (
    token: string,
    options?: {
      status?: ReadingStatus;
      favorite?: boolean;
      sort?: string;
      order?: string;
      limit?: number;
      offset?: number;
    },
  ) => {
    const params = new URLSearchParams();
    if (options?.status) params.set("status", options.status);
    if (options?.favorite !== undefined)
      params.set("favorite", String(options.favorite));
    if (options?.sort) params.set("sort", options.sort);
    if (options?.order) params.set("order", options.order);
    if (options?.limit) params.set("limit", String(options.limit));
    if (options?.offset) params.set("offset", String(options.offset));
    const qs = params.toString();
    return get(`/books/me${qs ? `?${qs}` : ""}`, token) as Promise<PaginatedBooksWithInteraction>;
  },

  getReadingActivity: (year: number, token: string) =>
    get(`/books/reading-activity?year=${year}`, token) as Promise<
      { date: string; seconds: number }[]
    >,
};

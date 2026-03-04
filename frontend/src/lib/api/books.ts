import { get, post, put, del } from './client';
import type { BookOut, ExternalMetadataOut, HighlightOut, InteractionOut, ProgressOut } from '$lib/types';

export const booksApi = {
  search: (query: string, token: string) =>
    get(`/books?q=${encodeURIComponent(query)}`, token) as Promise<BookOut[]>,

  upload: (file: File, token: string, libraryId?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (libraryId) formData.append('library_id', libraryId);
    return fetch('/api/books', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    }).then(async (res) => {
      if (!res.ok) {
        const err = await res.json().catch(() => ({})) as { detail?: string };
        throw new Error(err.detail || `HTTP ${res.status}`);
      }
      return res.json() as Promise<BookOut>;
    });
  },

  get: (bookId: string, token: string) =>
    get(`/books/${bookId}`, token) as Promise<BookOut>,

  updateMetadata: (bookId: string, data: {
    title?: string | null;
    authors?: string[] | null;
    publisher?: string | null;
    description?: string | null;
    published_date?: string | null;
  }, token: string) =>
    put(`/books/${bookId}/metadata`, data, token) as Promise<BookOut>,

  delete: (bookId: string, token: string) =>
    del(`/books/${bookId}`, token),

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

  getProgress: (bookId: string, token: string) =>
    get(`/books/${bookId}/progress`, token) as Promise<ProgressOut>,

  updateProgress: (bookId: string, data: {
    cfi: string;
    percentage: number;
    font_size?: number;
    section_index?: number;
    section_page?: number;
  }, token: string) =>
    put(`/books/${bookId}/progress`, data, token),

  getHighlights: (bookId: string, token: string) =>
    get(`/books/${bookId}/highlights`, token) as Promise<HighlightOut[]>,

  createHighlight: (
    bookId: string,
    data: { cfi_range: string; text: string; color: string; note?: string },
    token: string
  ) => post(`/books/${bookId}/highlights`, data, token) as Promise<HighlightOut>,

  updateHighlight: (
    bookId: string,
    highlightId: string,
    data: { color?: string; note?: string },
    token: string
  ) => put(`/books/${bookId}/highlights/${highlightId}`, data, token) as Promise<HighlightOut>,

  deleteHighlight: (bookId: string, highlightId: string, token: string) =>
    del(`/books/${bookId}/highlights/${highlightId}`, token),

  getAllHighlights: (token: string) =>
    get('/highlights', token) as Promise<HighlightOut[]>,
};

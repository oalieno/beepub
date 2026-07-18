import { get, post, put, del } from "./client";
import type {
  LibraryOut,
  PaginatedBooksWithInteraction,
  PaginatedFeed,
  PaginatedSeries,
} from "$lib/types";

export interface FeedParams {
  search?: string;
  author?: string;
  tag?: string;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
}

export function feedQuery(options?: FeedParams): string {
  const params = new URLSearchParams();
  if (options?.search) params.set("search", options.search);
  if (options?.author) params.set("author", options.author);
  if (options?.tag) params.set("tag", options.tag);
  if (options?.sort) params.set("sort", options.sort);
  if (options?.order) params.set("order", options.order);
  if (options?.limit != null) params.set("limit", String(options.limit));
  if (options?.offset != null) params.set("offset", String(options.offset));
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

export const librariesApi = {
  list: () => get("/libraries") as Promise<LibraryOut[]>,

  get: (id: string) => get(`/libraries/${id}`) as Promise<LibraryOut>,

  create: (data: { name: string; description?: string }) =>
    post("/libraries", data) as Promise<LibraryOut>,

  update: (id: string, data: { name?: string; description?: string }) =>
    put(`/libraries/${id}`, data) as Promise<LibraryOut>,

  delete: (id: string) => del(`/libraries/${id}`),

  getBooks: (
    id: string,
    options?: {
      search?: string;
      author?: string;
      tag?: string;
      series?: string;
      format?: string;
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
    if (options?.format) params.set("format", options.format);
    if (options?.sort) params.set("sort", options.sort);
    if (options?.order) params.set("order", options.order);
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.offset != null) params.set("offset", String(options.offset));
    const qs = params.toString();
    return get(
      `/libraries/${id}/books${qs ? `?${qs}` : ""}`,
    ) as Promise<PaginatedBooksWithInteraction>;
  },

  getSeries: (
    id: string,
    options?: { search?: string; limit?: number; offset?: number },
  ) => {
    const params = new URLSearchParams();
    if (options?.search) params.set("search", options.search);
    if (options?.limit != null) params.set("limit", String(options.limit));
    if (options?.offset != null) params.set("offset", String(options.offset));
    const qs = params.toString();
    return get(
      `/libraries/${id}/series${qs ? `?${qs}` : ""}`,
    ) as Promise<PaginatedSeries>;
  },

  getFeed: (id: string, options?: FeedParams) =>
    get(`/libraries/${id}/feed${feedQuery(options)}`) as Promise<PaginatedFeed>,
};

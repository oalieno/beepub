import { get } from "./client";

export interface SemanticSearchResult {
  book_id: string;
  book_title: string;
  book_author: string | null;
  passage: string;
  spine_index: number;
  char_offset_start: number;
  char_offset_end: number;
  similarity: number;
}

export interface SemanticSearchResponse {
  results: SemanticSearchResult[];
  query: string;
}

export const searchApi = {
  semantic(
    q: string,
    token: string,
    limit = 10,
  ): Promise<SemanticSearchResponse> {
    return get(
      `/search/semantic?q=${encodeURIComponent(q)}&limit=${limit}`,
      token,
    ) as Promise<SemanticSearchResponse>;
  },
};

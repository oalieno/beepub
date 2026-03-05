export enum UserRole {
  User = 'user',
  Admin = 'admin',
}

export enum LibraryVisibility {
  Public = 'public',
  Private = 'private',
}

export interface UserOut {
  id: string; // UUID
  username: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface LibraryOut {
  id: string;
  name: string;
  description: string | null;
  cover_image: string | null;
  visibility: LibraryVisibility;
  created_by: string;
  created_at: string;
}

export interface BookOut {
  id: string;
  file_size: number;
  format: string;
  cover_path: string | null;
  epub_title: string | null;
  epub_authors: string[] | null;
  epub_publisher: string | null;
  epub_language: string | null;
  epub_isbn: string | null;
  epub_description: string | null;
  epub_published_date: string | null;
  title: string | null;
  authors: string[] | null;
  publisher: string | null;
  description: string | null;
  published_date: string | null;
  display_title: string | null;
  display_authors: string[] | null;
  added_by: string;
  created_at: string;
}

export interface BookshelfOut {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  created_at: string;
}

export interface ExternalMetadataOut {
  id: string;
  book_id: string;
  source: string;
  source_url: string | null;
  rating: number | null;
  rating_count: number | null;
  reviews: Array<{ content: string; author?: string; rating?: number }> | null;
  fetched_at: string;
}

export interface HighlightOut {
  id: string;
  book_id: string;
  user_id: string;
  cfi_range: string;
  text: string;
  color: string;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProgressOut {
  cfi: string | null;
  percentage: number | null;
  current_page: number | null;
  font_size: number | null;
  section_index: number | null;
  section_page: number | null;
  section_page_counts: number[] | null;
  total_pages: number | null;
  last_read_at: string | null;
}

export interface InteractionOut {
  rating: number | null;
  is_favorite: boolean;
  reading_progress: ProgressOut | null;
  updated_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface IllustrationOut {
  id: string;
  user_id: string;
  book_id: string;
  cfi_range: string;
  text: string;
  style_prompt: string | null;
  custom_prompt: string | null;
  status: 'pending' | 'generating' | 'completed' | 'failed';
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface StylePromptOut {
  key: string;
  label: string;
  description: string;
}

export interface AdminStats {
  users: number;
  books: number;
  libraries: number;
}

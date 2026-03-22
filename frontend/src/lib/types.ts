export enum UserRole {
  User = "user",
  Admin = "admin",
}

export enum LibraryVisibility {
  Public = "public",
  Private = "private",
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
  calibre_path: string | null;
  created_by: string;
  created_at: string;
  book_count: number;
  preview_book_ids: string[];
}

export interface AiBookTag {
  id: string;
  tag: string;
  label: string;
  category: "genre" | "mood" | "topic";
  confidence: number;
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
  epub_series: string | null;
  epub_series_index: number | null;
  epub_tags: string[] | null;
  title: string | null;
  authors: string[] | null;
  publisher: string | null;
  description: string | null;
  published_date: string | null;
  series: string | null;
  series_index: number | null;
  tags: string[] | null;
  word_count: number | null;
  display_title: string | null;
  display_authors: string[] | null;
  display_series: string | null;
  display_series_index: number | null;
  display_tags: string[] | null;
  ai_tags?: AiBookTag[];
  calibre_id: number | null;
  calibre_added_at: string | null;
  added_by: string;
  created_at: string;
  library_id: string | null;
}

export interface TagBrowseSection {
  tag: string;
  label: string;
  category: string;
  book_count: number;
  books: BookOut[];
}

export interface PaginatedBooks {
  items: BookOut[];
  total: number;
}

export interface BookWithInteractionOut extends BookOut {
  reading_status: ReadingStatus | null;
  is_favorite: boolean;
  reading_percentage: number | null;
  last_read_at: string | null;
}

export interface PaginatedBooksWithInteraction {
  items: BookWithInteractionOut[];
  total: number;
}

export interface BookshelfOut {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  created_at: string;
  book_count: number;
  preview_book_ids: string[];
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

export type ReadingStatus =
  | "want_to_read"
  | "currently_reading"
  | "read"
  | "did_not_finish";

export interface InteractionOut {
  rating: number | null;
  is_favorite: boolean;
  reading_progress: ProgressOut | null;
  reading_status: ReadingStatus | null;
  started_at: string | null;
  finished_at: string | null;
  notes: string | null;
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
  status: "pending" | "generating" | "completed" | "failed";
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface StylePromptOut {
  key: string;
  label: string;
  description: string;
}

export interface EpubImageInfo {
  path: string;
  name: string;
}

export interface ReferenceImageInput {
  source: "epub" | "illustration";
  path: string;
}

export interface AdminStats {
  users: number;
  books: number;
  libraries: number;
}

export interface AdminSettings {
  timezone: string;
  metadata_refresh_enabled: string;
  metadata_refresh_hour: string;
  metadata_refresh_interval_days: string;
  metadata_refresh_cooldown_days: string;
  gemini_api_key: string;
  openai_api_key: string;
  openai_base_url: string;
  companion_provider: string;
  companion_model: string;
  tag_provider: string;
  tag_model: string;
  image_provider: string;
  image_model: string;
  embedding_provider: string;
  embedding_model: string;
}

export interface AiStatus {
  companion: boolean;
  tag: boolean;
  image: boolean;
}

export interface CalibreLibraryInfo {
  path: string;
  name: string;
  calibre_book_count: number | null;
  linked: boolean;
  library_id: string | null;
  library_name: string | null;
}

export interface CalibreSyncStatus {
  status: "running" | "completed" | "failed";
  total: number;
  processed: number;
  added: number;
  updated: number;
  unchanged: number;
  skipped: number;
  errors: string[];
}

export interface CalibreLibraryStatus {
  library_id: string;
  library_name: string;
  calibre_path: string;
  calibre_book_count: number | null;
  imported_book_count: number;
  sync: CalibreSyncStatus | null;
}

export interface CompanionMessageOut {
  id: string;
  role: "user" | "assistant";
  content: string;
  selected_text: string | null;
  cfi_range: string | null;
  created_at: string;
}

export interface CompanionConversationSummary {
  id: string;
  book_id: string;
  title: string | null;
  created_at: string;
  updated_at: string;
}

export interface JobProgress {
  status: "running" | "completed" | "failed";
  total: number;
  processed: number;
  failed: number;
}

export interface JobStatus {
  key: string;
  label: string;
  description: string;
  total: number;
  missing: number;
  active: boolean;
  progress: JobProgress | null;
}

export interface AllJobsResponse {
  jobs: JobStatus[];
}

export interface CompanionConversationOut {
  id: string;
  book_id: string;
  title: string | null;
  messages: CompanionMessageOut[];
  created_at: string;
}

export interface ReadingStats {
  current_streak: number;
  longest_streak: number;
  today_seconds: number;
  goal_seconds: number | null;
}

export interface LlmUsageByFeature {
  feature: string;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  call_count: number;
  estimated_cost: number;
}

export interface LlmUsageByDay {
  day: string;
  feature: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  call_count: number;
}

export interface LlmUsageByUser {
  username: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  call_count: number;
}

export interface LlmUsageResponse {
  period: string;
  since: string;
  by_feature: LlmUsageByFeature[];
  by_user: LlmUsageByUser[];
  by_day: LlmUsageByDay[];
  totals: {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    call_count: number;
    estimated_cost: number;
  };
}

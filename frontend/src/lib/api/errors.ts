/**
 * What a failed request says, in the reader's language.
 *
 * The backend names each error it expects a reader to see with a code
 * (`backend/app/errors.py`) and sends it beside the English sentence:
 * `{ detail, code }`. The message is picked by the code; an error
 * without one, or with a code this build does not know, is shown as the
 * sentence it came with.
 *
 * A backend test holds this list against the backend's: a code on one
 * side only fails it.
 */
import * as m from "#lib/paraglide/messages.js";

const MESSAGES: Record<string, () => string> = {
  access_denied: () => m.error_access_denied(),
  account_disabled: () => m.error_account_disabled(),
  illustration_exists: () => m.error_illustration_exists(),
  token_name_taken: () => m.profile_api_token_name_taken(),
  book_in_shelf: () => m.error_book_in_shelf(),
  move_book_in_work: () => m.error_move_book_in_work(),
  book_not_found: () => m.error_book_not_found(),
  book_not_in_shelf: () => m.error_book_not_in_shelf(),
  move_into_calibre: () => m.error_move_into_calibre(),
  move_out_of_calibre: () => m.error_move_out_calibre(),
  bookshelf_not_found: () => m.error_bookshelf_not_found(),
  calibre_already_linked: () => m.error_calibre_already_linked(),
  cannot_delete_self: () => m.error_cannot_delete_self(),
  cannot_demote_last_admin: () => m.error_cannot_demote_last_admin(),
  calibre_no_upload: () => m.error_calibre_no_upload(),
  conversation_not_found: () => m.error_conversation_not_found(),
  cover_not_found: () => m.error_cover_not_found(),
  wrong_password: () => m.error_wrong_password(),
  description_too_long: () => m.error_description_too_long(),
  download_permission_required: () => m.error_download_permission(),
  metadata_not_found: () => m.error_metadata_not_found(),
  file_not_found: () => m.error_file_not_found(),
  gemini_not_configured: () => m.error_gemini_not_configured(),
  goal_out_of_range: () => m.error_goal_range(),
  highlight_not_found: () => m.error_highlight_not_found(),
  illustration_not_found: () => m.error_illustration_not_found(),
  image_not_found: () => m.error_image_not_found(),
  image_not_ready: () => m.error_image_not_ready(),
  invalid_credentials: () => m.error_invalid_credentials(),
  invalid_source: () => m.error_invalid_source(),
  library_not_found: () => m.error_library_not_found(),
  no_metadata_db: () => m.error_no_metadata_db(),
  not_calibre: () => m.error_not_calibre(),
  upload_format: () => m.error_upload_format(),
  upload_drm: () => m.error_upload_drm(),
  txt_empty: () => m.error_txt_empty(),
  openai_not_configured: () => m.error_openai_not_configured(),
  path_not_in_epub: () => m.error_path_not_in_epub(),
  rating_out_of_range: () => m.error_rating_range(),
  registration_closed: () => m.error_registration_closed(),
  report_not_found: () => m.error_report_not_found(),
  search_not_configured: () => m.error_search_not_configured(),
  sync_in_progress: () => m.error_sync_in_progress(),
  user_not_found: () => m.error_user_not_found(),
  username_exists: () => m.error_username_exists(),
  too_many_attempts: () => m.error_too_many_attempts(),
};

/** The message for a failed response's body, or `null` if it says nothing. */
export function errorMessage(body: {
  detail?: unknown;
  code?: unknown;
}): string | null {
  const known = typeof body.code === "string" ? MESSAGES[body.code] : null;
  if (known) return known();
  return body.detail ? String(body.detail) : null;
}

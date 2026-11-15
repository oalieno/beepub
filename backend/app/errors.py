"""The errors a reader is told about in their own language.

A failed request answers ``{"detail": <English sentence>, "code": <code>}``.
The frontend picks its translation by ``code`` (``frontend/src/lib/api/
errors.ts``), so the sentence here can be reworded freely; the code
cannot. Every error with a translation is listed here once and raised as
``raise errors.BOOK_NOT_FOUND()``. An error nobody translates stays a
plain ``HTTPException`` and is shown as its English sentence.

``tests/test_error_codes.py`` holds this list against the frontend's.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """An ``HTTPException`` that also names itself by a stable code."""

    def __init__(
        self,
        code: str,
        status_code: int,
        detail: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code


@dataclass(frozen=True)
class Problem:
    code: str
    status_code: int
    detail: str

    def __call__(
        self,
        *,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> ApiError:
        """A fresh exception to raise. ``status_code`` is for the few
        places that have always answered this error with another status."""
        return ApiError(
            self.code, status_code or self.status_code, self.detail, headers
        )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code},
        status_code=exc.status_code,
        headers=exc.headers,
    )


ACCESS_DENIED = Problem("access_denied", 403, "Access denied")
ACCOUNT_DISABLED = Problem("account_disabled", 400, "Account is disabled")
ILLUSTRATION_EXISTS = Problem(
    "illustration_exists", 409, "An illustration already exists for this text selection"
)
TOKEN_NAME_TAKEN = Problem(
    "token_name_taken", 409, "A token with this name already exists"
)
BOOK_IN_SHELF = Problem("book_in_shelf", 409, "Book already in shelf")
MOVE_BOOK_IN_WORK = Problem(
    "move_book_in_work",
    409,
    "Book is part of a Work. Dissolve the Work first, or move all its editions together.",
)
BOOK_NOT_FOUND = Problem("book_not_found", 404, "Book not found")
BOOK_NOT_IN_SHELF = Problem("book_not_in_shelf", 404, "Book not in shelf")
MOVE_INTO_CALIBRE = Problem(
    "move_into_calibre", 403, "Cannot move books into a Calibre library"
)
MOVE_OUT_OF_CALIBRE = Problem(
    "move_out_of_calibre", 403, "Cannot move books out of a Calibre library"
)
BOOKSHELF_NOT_FOUND = Problem("bookshelf_not_found", 404, "Bookshelf not found")
CALIBRE_ALREADY_LINKED = Problem(
    "calibre_already_linked", 409, "Calibre library already linked"
)
CANNOT_DELETE_SELF = Problem("cannot_delete_self", 400, "Cannot delete yourself")
CANNOT_DEMOTE_LAST_ADMIN = Problem(
    "cannot_demote_last_admin", 400, "Cannot demote the last admin"
)
CALIBRE_NO_UPLOAD = Problem(
    "calibre_no_upload", 403, "Cannot upload to a Calibre library"
)
CONVERSATION_NOT_FOUND = Problem(
    "conversation_not_found", 404, "Conversation not found"
)
COVER_NOT_FOUND = Problem("cover_not_found", 404, "Cover not found")
WRONG_PASSWORD = Problem("wrong_password", 400, "Current password is incorrect")
DESCRIPTION_TOO_LONG = Problem(
    "description_too_long", 422, "Description must be 2000 characters or less"
)
DOWNLOAD_PERMISSION_REQUIRED = Problem(
    "download_permission_required", 403, "Download permission required"
)
METADATA_NOT_FOUND = Problem("metadata_not_found", 404, "External metadata not found")
FILE_NOT_FOUND = Problem("file_not_found", 404, "File not found")
GEMINI_NOT_CONFIGURED = Problem(
    "gemini_not_configured", 400, "Gemini API key not configured"
)
GOAL_OUT_OF_RANGE = Problem(
    "goal_out_of_range",
    422,
    "Goal must be between 60 and 86400 seconds (1 min to 24 hrs)",
)
HIGHLIGHT_NOT_FOUND = Problem("highlight_not_found", 404, "Highlight not found")
ILLUSTRATION_NOT_FOUND = Problem(
    "illustration_not_found", 404, "Illustration not found"
)
IMAGE_NOT_FOUND = Problem("image_not_found", 404, "Image file not found")
IMAGE_NOT_READY = Problem("image_not_ready", 404, "Image not ready")
INVALID_CREDENTIALS = Problem("invalid_credentials", 401, "Invalid credentials")
INVALID_SOURCE = Problem("invalid_source", 400, "Invalid source")
LIBRARY_NOT_FOUND = Problem("library_not_found", 404, "Library not found")
NO_METADATA_DB = Problem("no_metadata_db", 400, "No metadata.db found at path")
NOT_CALIBRE = Problem("not_calibre", 400, "Not a Calibre library")
UPLOAD_FORMAT = Problem(
    "upload_format", 415, "Only EPUB, TXT, MOBI, AZW3 or CBZ files are supported"
)
UPLOAD_DRM = Problem("upload_drm", 400, "The book is DRM-protected")
TXT_EMPTY = Problem("txt_empty", 400, "The TXT file has no text")
OPENAI_NOT_CONFIGURED = Problem(
    "openai_not_configured", 400, "OpenAI base URL not configured"
)
PATH_NOT_IN_EPUB = Problem("path_not_in_epub", 404, "Path not found in EPUB")
RATING_OUT_OF_RANGE = Problem(
    "rating_out_of_range", 400, "Rating must be 0.5-5 in 0.5 steps"
)
REGISTRATION_CLOSED = Problem(
    "registration_closed", 403, "Registration is currently closed"
)
REPORT_NOT_FOUND = Problem("report_not_found", 404, "Report not found")
SEARCH_NOT_CONFIGURED = Problem(
    "search_not_configured", 503, "Semantic search is not configured"
)
SYNC_IN_PROGRESS = Problem("sync_in_progress", 409, "Sync already in progress")
USER_NOT_FOUND = Problem("user_not_found", 404, "User not found")
USERNAME_EXISTS = Problem("username_exists", 409, "Username already exists")
TOO_MANY_ATTEMPTS = Problem(
    "too_many_attempts", 429, "Too many failed attempts. Try again later."
)

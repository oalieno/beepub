import os
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging import setup_logging
from app.routers import (
    admin,
    auth,
    books,
    bookshelves,
    companion,
    highlights,
    illustrations,
    jobs,
    libraries,
    search,
    tags,
)
from app.services.auth import decode_token

setup_logging(log_format=os.environ.get("LOG_FORMAT", "console"))

app = FastAPI(title="BeePub API", version="1.0.0")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        ctx = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
        }

        # Extract user_id from JWT if present
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            payload = decode_token(auth_header[7:])
            if payload and payload.get("sub"):
                ctx["user_id"] = payload["sub"]

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(**ctx)

        logger = structlog.get_logger()
        logger.info("request_started")

        response: Response = await call_next(request)

        logger.info("request_finished", status_code=response.status_code)
        structlog.contextvars.clear_contextvars()
        return response


app.add_middleware(RequestContextMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(libraries.router)
app.include_router(books.router)
app.include_router(bookshelves.router)
app.include_router(admin.router)
app.include_router(admin.ai_router)
app.include_router(highlights.router)
app.include_router(illustrations.router)
app.include_router(tags.router)
app.include_router(companion.router)
app.include_router(search.router)
app.include_router(jobs.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

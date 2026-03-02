from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import auth, libraries, books, bookshelves, admin, highlights

app = FastAPI(title="BeePub API", version="1.0.0")

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
app.include_router(highlights.router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}

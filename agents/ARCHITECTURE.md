# BeePub 架構

## 目錄結構

```
beepub/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── nginx/nginx.conf
├── agents/                    # AI 協作文件
│   ├── OVERVIEW.md
│   ├── ARCHITECTURE.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── FRONTEND.md
│   └── debug/                 # Debug 記錄
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/env.py
│   ├── alembic/versions/
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── deps.py
│       ├── models/
│       │   ├── __init__.py  (re-export all)
│       │   ├── base.py
│       │   ├── user.py
│       │   ├── library.py
│       │   ├── book.py
│       │   ├── bookshelf.py
│       │   └── reading.py  (highlights, reading_progress)
│       ├── schemas/
│       │   ├── auth.py, user.py, library.py, book.py, bookshelf.py, reading.py
│       ├── routers/
│       │   ├── auth.py, libraries.py, books.py, bookshelves.py, reading.py, admin.py
│       ├── vendor/
│       │   └── ebooklib/  (vendored, 修改版)
│       └── services/
│           ├── auth.py, epub_parser.py, storage.py, metadata_queue.py
├── metadata-daemon/
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── daemon/
│       ├── main.py, config.py, database.py, queue.py, scheduler.py
│       └── sources/
│           ├── base.py, goodreads.py, readmoo.py, kobo_tw.py
└── frontend/
    ├── Dockerfile
    ├── package.json, svelte.config.js, vite.config.ts
    └── src/
        ├── app.html, app.css, app.d.ts
        ├── hooks.server.ts
        ├── lib/
        │   ├── types.ts
        │   ├── api/ (client.ts, auth.ts, books.ts, libraries.ts, bookshelves.ts)
        │   ├── stores/ (auth.ts, toast.ts)
        │   ├── epubjs/              # epub.js v0.3.93 本地 fork
        │   │   ├── epub.js          # 入口
        │   │   ├── managers/default/index.js  # 核心修改
        │   │   └── ...
        │   └── components/
        │       ├── ui/              # shadcn-svelte 元件
        │       ├── BookCard.svelte, BookGrid.svelte, Toast.svelte
        │       ├── Modal.svelte, StarRating.svelte, Navbar.svelte
        │       ├── DatePicker.svelte, ReadingActivityHeatmap.svelte
        │       └── reader/ (EpubReader.svelte, Toolbar.svelte, HighlightMenu.svelte)
        └── routes/
            ├── +layout.svelte, +layout.server.ts
            ├── login/
            ├── libraries/[id]/
            ├── books/[id]/read/
            ├── bookshelves/[id]/
            └── admin/ (libraries/[id]/, users/)
```

## Docker Compose 服務

```yaml
services:
  postgres:   postgres:16-alpine, volume: postgres_data
  redis:      redis:7-alpine
  backend:    FastAPI, port 8000 (internal), volumes: books, covers
  metadata-daemon: APScheduler worker
  frontend:   SvelteKit Node, port 3000 (internal)
  nginx:      port ${PORT:-80}, proxy /api/* → backend, /* → frontend
              static /covers/* → filesystem
```

## Auth 流程

1. 登入：POST /api/auth/login → JWT access token (預設 7 天)
2. 前端存在 cookie（非 httpOnly，讓 SvelteKit server 可讀）+ localStorage
3. SvelteKit `hooks.server.ts` 讀 cookie，呼叫 `GET /api/auth/me` 驗證
4. 將 user 資訊存入 `event.locals.user`
5. 未認證用戶一律 redirect `/login`（hooks.server.ts 統一處理）
6. Client-side API client 遇到 401 自動清除 token 並 redirect `/login`

## 圖書館存取邏輯

```python
# 管理員：看到所有圖書館
# 一般使用者：public + private where user in library_access
def get_accessible_libraries(user):
    if user.role == "admin":
        return all libraries
    return libraries where:
        visibility == PUBLIC
        OR (visibility == PRIVATE AND library_access.user_id == user.id)
```

## Metadata Daemon 架構

```
Redis Queue (LIST: beepub:metadata:queue)
  ← backend 推入: {"book_id": "uuid", "priority": "high"|"normal"}

Daemon Worker:
  BRPOP beepub:metadata:queue  (blocking pop)
  for each source in [goodreads, readmoo, kobo_tw]:
    result = source.fetch(book)
    upsert external_metadata

APScheduler (每日 3:00 AM):
  SELECT all books
  推入全部到 queue (priority=normal)
```

### Source 模組介面
```python
class AbstractMetadataSource(ABC):
    source_name: ClassVar[str]
    async def search(self, title: str, authors: list[str], isbn: str | None) -> list[SearchResult]
    async def fetch(self, url: str) -> FetchResult  # rating, rating_count, reviews
```

### 各來源策略
| 來源 | 方法 | 匹配依據 |
|------|------|----------|
| Goodreads | httpx + BS4 (JSON-LD) | ISBN → title+author 模糊匹配 |
| Readmoo | httpx + BS4 (搜尋 API + 詳細頁) | title+author |
| Kobo TW | httpx + BS4 (JSON-LD) | ISBN → title+author |

## 驗證方式

```bash
cp .env.example .env  # 填入 POSTGRES_PASSWORD, SECRET_KEY
docker compose up -d
docker compose ps

# 測試 API
curl -X POST http://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"changeme"}'
```

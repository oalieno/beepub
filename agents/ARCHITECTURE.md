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
│       ├── database.py          # get_db() + create_task_session()
│       ├── celeryapp.py         # Celery app 設定 + beat schedule
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
│       ├── services/
│       │   ├── auth.py, epub_parser.py, storage.py, calibre.py, epub_text.py
│       │   └── metadata_sources/
│       │       ├── base.py, goodreads.py, readmoo.py
│       └── tasks/               # Celery tasks
│           ├── metadata.py      # fetch_metadata, check_and_schedule_refresh
│           └── wordcount.py     # compute_word_count
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
  worker:     Celery worker (共用 backend image), concurrency=2
  beat:       Celery beat scheduler (共用 backend image)
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

## Celery 任務隊列架構

```
Redis (broker + result backend)

Celery Worker (prefork, concurrency=2):
  - fetch_metadata(book_id)        從 Goodreads/Readmoo 爬取 metadata
  - compute_word_count(book_id)    解析 EPUB 計算字數
  - check_and_schedule_refresh()   定期排程 metadata 更新

Celery Beat:
  每小時執行 check_and_schedule_refresh，根據 DB 設定決定是否觸發批次更新
```

### Celery task 與 async DB 的整合
Celery worker 是 sync (prefork)，但 DB 用 async SQLAlchemy。
每個 task 裡用 `asyncio.run()` 跑 async 程式碼，並用 `create_task_session()`
建立獨立 engine（不共用 FastAPI 的全域 engine），避免 asyncpg 跨 event loop 衝突。

### Metadata Source 模組介面
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

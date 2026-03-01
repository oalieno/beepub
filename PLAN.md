# BeePub 實作計畫

## Context
建立自架電子書管理系統，支援多人使用、多虛擬圖書館、線上閱讀、螢光筆、metadata 爬蟲。
部署方式：Docker Compose on NAS。

確認需求：
- 帳密登入，首個注冊使用者自動成為管理員
- 多人，管理員控制圖書館存取（public / private + 白名單）
- 無 DRM epub
- 新書上傳後自動觸發 metadata 爬取

---

## 目錄結構

```
beepub/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── nginx/nginx.conf
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/env.py
│   ├── alembic/versions/001_initial_schema.py
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
│       │   └── reading.py  (highlights, reading_progress in user_book_interactions)
│       ├── schemas/
│       │   ├── auth.py, user.py, library.py, book.py, bookshelf.py, reading.py
│       ├── routers/
│       │   ├── auth.py, libraries.py, books.py, bookshelves.py, reading.py, admin.py
│       ├── vendor/
│       │   └── ebooklib/  (vendored from github.com/aerkalov/ebooklib, 修改版)
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
    ├── tailwind.config.js, postcss.config.js
    └── src/
        ├── app.html, app.css, app.d.ts
        ├── hooks.server.ts
        ├── lib/
        │   ├── types.ts
        │   ├── api/ (client.ts, auth.ts, books.ts, libraries.ts, bookshelves.ts)
        │   ├── stores/ (auth.ts, toast.ts)
        │   └── components/
        │       ├── BookCard.svelte, BookGrid.svelte, Toast.svelte
        │       ├── Modal.svelte, StarRating.svelte, Navbar.svelte
        │       └── reader/ (EpubReader.svelte, Toolbar.svelte, HighlightMenu.svelte)
        └── routes/
            ├── +layout.svelte, +layout.server.ts, +page.svelte
            ├── login/
            ├── libraries/[id]/
            ├── books/[id]/read/
            ├── bookshelves/[id]/
            └── admin/ (libraries/[id]/, users/)
```

---

## Tech Stack

| 層 | 技術 |
|----|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic |
| Auth | python-jose (JWT HS256), passlib[bcrypt] |
| DB | PostgreSQL 16, asyncpg driver |
| Queue | Redis 7, redis-py |
| epub 解析 | ebooklib (vendored, 修改版), Pillow (封面) |
| Daemon 排程 | APScheduler 3 |
| 爬蟲 | httpx, BeautifulSoup4, rapidfuzz (模糊匹配) |
| Frontend | SvelteKit (@sveltejs/adapter-node), TailwindCSS 3 |
| epub 閱讀器 | epubjs |
| Icons | lucide-svelte |

---

## 資料庫 Schema

### users
```
id uuid PK | username varchar unique | email varchar unique
password_hash varchar | role enum(admin,user) | is_active bool | created_at
```

### libraries
```
id uuid PK | name varchar | description text | cover_image varchar
visibility enum(public,private) | created_by uuid→users | created_at
```

### library_access  ← private 圖書館白名單
```
library_id uuid→libraries | user_id uuid→users | granted_by uuid→users | granted_at
PK(library_id, user_id)
```

### library_books
```
library_id uuid→libraries | book_id uuid→books | added_by uuid→users | added_at
PK(library_id, book_id)
```

### books
```
id uuid PK | file_path varchar | file_size bigint | format varchar
cover_path varchar
-- EPUB 原始 metadata
epub_title, epub_authors text[], epub_publisher, epub_language
epub_isbn, epub_description, epub_published_date
-- 手動覆寫（優先顯示）
title, authors text[], publisher, description, published_date
-- 計算欄位（view 或 property）
display_title = COALESCE(title, epub_title)
display_authors = COALESCE(authors, epub_authors)
added_by uuid→users | added_at
```

### external_metadata
```
id uuid PK | book_id uuid→books | source enum(goodreads,readmoo,kobo_tw)
source_url varchar | rating numeric(3,2) | rating_count int
reviews jsonb [{author,content,rating,date}] | raw_data jsonb | fetched_at
UNIQUE(book_id, source)
```

### bookshelves
```
id uuid PK | user_id uuid→users | name varchar | description text
is_public bool | created_at
```

### bookshelf_books
```
bookshelf_id uuid | book_id uuid | sort_order int | added_at
PK(bookshelf_id, book_id)
```

### user_book_interactions
```
user_id uuid→users | book_id uuid→books
rating smallint (1-5, nullable) | is_favorite bool
reading_progress jsonb {cfi, percentage, last_read_at}
updated_at
PK(user_id, book_id)
```

### highlights
```
id uuid PK | user_id uuid→users | book_id uuid→books
cfi_range varchar | text text | color varchar
note text (nullable) | created_at | updated_at
```

---

## Backend API

### Auth
```
POST /api/auth/register   body:{username,email,password}
POST /api/auth/login      body:{username,password} → {access_token, user}
GET  /api/auth/me
```

### Libraries
```
GET    /api/libraries                    可見的圖書館列表（public + 白名單）
POST   /api/libraries                    [admin]
GET    /api/libraries/{id}
PUT    /api/libraries/{id}               [admin]
DELETE /api/libraries/{id}               [admin]
GET    /api/libraries/{id}/books         帶搜尋/排序
POST   /api/libraries/{id}/books         加入書籍 [admin]
DELETE /api/libraries/{id}/books/{bid}   [admin]
GET    /api/libraries/{id}/members       [admin] private 圖書館白名單
POST   /api/libraries/{id}/members       [admin]
DELETE /api/libraries/{id}/members/{uid} [admin]
```

### Books
```
GET    /api/books              全域搜尋（有權限存取的書）
POST   /api/books              上傳單本 epub（multipart）
POST   /api/books/bulk         上傳多本
GET    /api/books/{id}
PUT    /api/books/{id}/metadata 手動覆寫 metadata
DELETE /api/books/{id}         [admin]
GET    /api/books/{id}/file    串流 epub 檔案
GET    /api/books/{id}/cover
POST   /api/books/{id}/refresh 手動觸發 metadata 爬取
GET    /api/books/{id}/external 取得外部 metadata（評分書評）
```

### 使用者互動
```
PUT  /api/books/{id}/rating    body:{rating:1-5|null}
PUT  /api/books/{id}/favorite  body:{is_favorite:bool}
GET  /api/books/{id}/progress
PUT  /api/books/{id}/progress  body:{cfi,percentage}
GET  /api/books/{id}/highlights
POST /api/books/{id}/highlights body:{cfi_range,text,color,note?}
PUT  /api/books/{id}/highlights/{hid}
DELETE /api/books/{id}/highlights/{hid}
```

### Bookshelves
```
GET    /api/bookshelves
POST   /api/bookshelves
GET    /api/bookshelves/{id}
PUT    /api/bookshelves/{id}
DELETE /api/bookshelves/{id}
POST   /api/bookshelves/{id}/books    body:{book_id}
DELETE /api/bookshelves/{id}/books/{bid}
PUT    /api/bookshelves/{id}/books/reorder
```

### Admin
```
GET    /api/admin/users
PUT    /api/admin/users/{id}/role
DELETE /api/admin/users/{id}
GET    /api/admin/stats
```

---

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

---

## Auth 流程

1. 登入：POST /api/auth/login → JWT access token (30分鐘)
2. 前端存在 cookie（非 httpOnly，讓 SvelteKit server 可讀）
3. SvelteKit `hooks.server.ts` 讀 cookie，呼叫 `GET /api/auth/me` 驗證
4. 將 user 資訊存入 `event.locals.user`
5. 需要 auth 的 server load 檢查 `locals.user`，否則 redirect `/login`

---

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
| Goodreads | httpx + BS4 (JSON-LD 結構化資料) | ISBN → title+author 模糊匹配 |
| Readmoo | httpx + BS4 (搜尋 API + 詳細頁) | title+author |
| Kobo TW | httpx + BS4 (JSON-LD 結構化資料) | ISBN → title+author |

---

## 前端路由

```
/              首頁（最近新增、書架、統計）
/login
/libraries     所有可見圖書館
/libraries/[id] 圖書館書籍（搜尋、排序、篩選）
/books/[id]    書籍詳情（metadata、評分、書評）
/books/[id]/read  EPUB 閱讀器
/bookshelves   我的書架列表
/bookshelves/[id] 書架書籍
/admin         管理儀表板
/admin/libraries  管理圖書館（visibility、白名單）
/admin/libraries/[id] 管理特定圖書館
/admin/users   管理使用者（角色、停用）
```

---

## EPUB 閱讀器功能

- 使用 epubjs 在瀏覽器端渲染
- epub 從 `GET /api/books/{id}/file` 串流載入
- 進度：CFI 位置自動儲存（每30秒 + 翻頁時）
- 螢光筆：5色（黃/綠/藍/粉/橙），點選文字彈出選單
- 每個 highlight 可附加文字註解
- 字體切換：serif / sans-serif（透過 epubjs themes）
- 文字大小調整

---

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

---

## 實作順序

1. **基礎設施**：docker-compose, nginx, .env.example
2. **Backend 模型 & DB**：models, alembic migration
3. **Backend Auth**：register/login/me endpoints
4. **Backend 核心**：books (upload, epub parse, cover extract), libraries, bookshelves
5. **Backend 互動**：rating, favorite, highlights, reading progress
6. **Metadata Daemon**：queue worker, APScheduler, 3 source modules
7. **Frontend 基礎**：SvelteKit setup, auth, hooks, API client
8. **Frontend 頁面**：libraries, books detail, bookshelves
9. **Frontend 閱讀器**：epubjs 整合, highlights, 設定
10. **Frontend Admin**：圖書館管理, 使用者管理

---

## 已修復的重要問題

### EPUB 封面抓取（2026-03）
- **問題**：EPUB 3 格式書籍的封面無法正確識別，落回第一張圖片
- **根因**：ebooklib 在 parse manifest 時，image items 的 `properties` 屬性（`cover-image`）有讀取但未賦值給物件；且 `EpubCover` 的 `get_type()` 回傳 `ITEM_COVER` 而非 `ITEM_IMAGE`
- **修復**：
  1. 將 ebooklib vendor 到 `backend/app/vendor/ebooklib/`，在 `epub.py` 加入 `ei.properties = properties`
  2. `epub_parser.py` Method 2 改用 `book.get_items()` 全掃描配合 `properties` 欄位判斷

## 驗證方式

```bash
# 啟動服務
cp .env.example .env  # 填入 POSTGRES_PASSWORD, SECRET_KEY
docker compose up -d

# 確認服務健康
docker compose ps

# 測試 API
curl -X POST http://192.168.1.105:3333/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"changeme"}'

curl -X POST http://192.168.1.105:3333/api/auth/login \
  -d '{"username":"admin","password":"changeme"}'

# 上傳測試 epub
curl -X POST http://192.168.1.105:3333/api/books \
  -H "Authorization: Bearer <token>" \
  -F "file=@test.epub" -F "library_id=<id>"

# 確認 metadata daemon 有在工作
docker compose logs metadata-daemon
```
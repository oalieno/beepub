# 013 — Calibre Library Read-Only Import

## 功能概述

讓 BeePub 可以 read-only mount Calibre library 到 Docker container，直接讀取 Calibre 的 EPUB 書籍。不複製 EPUB 檔案，直接從 mount 路徑讀取。支援多個 Calibre library。

## 設計

- 每個 Calibre library 對應一個 BeePub 的 **特殊 read-only library**
- `libraries.calibre_path IS NOT NULL` 代表此 library 是 Calibre synced（不能手動上傳書）
- `books.calibre_id` 記錄 Calibre 的 `books.id`，用於 re-sync 比對
- 背景 sync 用 `asyncio.create_task()`，進度存 Redis
- Sync 時不觸發 metadata fetch（admin 可之後手動 refresh 單本）
- EPUB `file_path` 直接指向 Calibre mount 路徑（e.g. `/calibre/New/Author/Title (42601)/Book.epub`）
- Cover 複製到 BeePub 的 `/data/covers/` 目錄

## Calibre Library 結構

```
/calibre/{library_name}/
├── metadata.db                              # SQLite
├── Author Name/
│   └── Book Title (42601)/
│       ├── cover.jpg
│       ├── Book Title - Author.epub
│       └── metadata.opf
```

### Calibre SQLite Schema（重要）
- `books` 表：id, title, path, has_cover, pubdate（**沒有 isbn 欄位**）
- `data` 表：book FK, format (EPUB/PDF), name (檔名不含副檔名), uncompressed_size
- `identifiers` 表：book FK, type ('isbn'), val — ISBN 存在這裡
- `authors` 表 + `books_authors_link` 連結
- `comments` 表：book FK, text — 書籍描述
- `publishers` 表 + `books_publishers_link` 連結

EPUB 路徑 = `{calibre_root}/{books.path}/{data.name}.epub`

## DB Schema 變更

Migration: `006_add_calibre_fields.py`

```python
# libraries 表
calibre_path: String(500), nullable, unique

# books 表
calibre_id: Integer, nullable, indexed
```

## 後端檔案

### `backend/app/services/calibre.py`（新檔案）

| 函式 | 說明 |
|------|------|
| `scan_calibre_libraries()` | 掃描 `/calibre/` 下有 `metadata.db` 的目錄 |
| `read_calibre_books(calibre_dir)` | 讀 Calibre SQLite，JOIN books/data/authors/comments/publishers/identifiers |
| `sync_calibre_library(calibre_dir, library_id, admin_user_id)` | 背景 sync task |
| `get_sync_status(library_id)` | 從 Redis 讀 sync 進度 |

### Sync 流程

1. `asyncio.to_thread(read_calibre_books, calibre_dir)` — SQLite 讀取在 thread 執行
2. 自行建 db session（`AsyncSessionLocal()`），不用 request 的 session
3. 檢查 library 是否仍存在（可能在 sync 中被刪）
4. 查此 library 已匯入的書（by `calibre_id`）
5. 逐本處理：
   - 已存在 → 更新 file_path / title / authors（如有變更）
   - 新書 → 驗證 EPUB 存在 → `parse_epub_metadata()` → 複製 cover → 建 Book + LibraryBook
   - 找不到 EPUB → skip + 記錄 error
6. Redis 進度：`beepub:calibre:sync:{library_id}` → JSON `{status, total, processed, added, updated, unchanged, skipped, errors}`

### Admin API Endpoints（`backend/app/routers/admin.py`）

```
GET  /api/admin/calibre/libraries                    掃描可用的 Calibre library
POST /api/admin/calibre/libraries                    連結：建立 BeePub library + 首次 sync
POST /api/admin/calibre/libraries/{library_id}/sync  觸發 re-sync (202)
GET  /api/admin/calibre/libraries/{library_id}/status sync 進度 + 書數
```

### 保護邏輯

**上傳保護：**
- `POST /api/books`：上傳到 Calibre library 時拒絕（400）
- `POST /api/books/bulk`：同上
- `POST /api/libraries/{id}/books`：加書到 Calibre library 時拒絕

**刪除保護：**
- `DELETE /api/books/{id}`：`calibre_id IS NOT NULL` 的書不刪 EPUB 檔案（Calibre 管理的），cover 仍刪除
- `DELETE /api/libraries/{id}`：刪除 Calibre library 時，一併刪除所有 Book records 和 covers（但不刪 EPUB）

**SQLAlchemy 修正：**
- Library model 的 `accesses` 和 `library_books` relationships 加 `passive_deletes=True`
- 因為 DB FK 有 `ondelete="CASCADE"`，但 ORM 預設會嘗試 SET NULL，導致 `AssertionError: Dependency rule tried to blank-out primary key`

## 前端檔案

### 新頁面：`frontend/src/routes/admin/calibre/+page.svelte`
- 掃描可用 Calibre library 列表
- 「Link」按鈕 → 命名對話框 → 建立連結 + 首次 sync
- 已連結的 library 顯示 sync 狀態、progress bar、「Re-sync」按鈕
- 2 秒 polling 更新 sync 進度

### 修改的頁面
- `/admin` — 加 Calibre Import 連結卡片
- `/admin/libraries` — Calibre library 顯示 HardDrive badge
- `/libraries` — Calibre library 顯示 HardDrive icon
- `/libraries/[id]` — Calibre library 隱藏上傳按鈕、拖放區域

### Types & API
- `frontend/src/lib/types.ts` — 加 `CalibreLibraryInfo`, `CalibreSyncStatus`, `CalibreLibraryStatus`
- `frontend/src/lib/api/bookshelves.ts` — 加 `adminApi` 的 4 個 Calibre 方法

## 踩過的坑

### 1. Calibre 沒有 `books.isbn` 欄位
- 誤以為 Calibre 的 `books` 表有 `isbn` 欄位，實際上 ISBN 存在 `identifiers` 表
- 修正：`LEFT JOIN identifiers i ON i.book = b.id AND i.type = 'isbn'`，取 `i.val AS isbn`

### 2. Svelte 5 不支援 `onclick|self`
- Svelte 4 的 `on:click|self` 在 Svelte 5 無效
- 修正：`onclick={(e) => { if (e.target === e.currentTarget) { ... } }}`

### 3. Library 刪除 500 錯誤（passive_deletes）
- 錯誤：`AssertionError: Dependency rule tried to blank-out primary key column 'library_books.library_id'`
- 原因：DB FK 有 `ondelete="CASCADE"`，但 ORM 預設想 SET NULL
- 修正：`passive_deletes=True` on relationships

### 4. 刪除 Calibre library 時需要清理 Book records
- Calibre library 的書不在其他 library 中（是 sync 自動建立的）
- 刪除 library 時要：
  1. 查出所有 LibraryBook 的 book_id
  2. 刪除 cover 檔案（我們複製的）
  3. 刪除 Book records（不刪 EPUB，那是 Calibre 的）
  4. 再刪 Library（CASCADE 刪 LibraryBook）

### 5. Sync 中 library 被刪除
- 背景 task 開始時檢查 library 是否存在
- 如果已刪除，abort sync 並設狀態為 failed

## 驗證清單

1. `GET /api/admin/calibre/libraries` — 偵測到 mount 的 Calibre library
2. Link → 自動建 BeePub library + sync → 書出現在 library
3. 封面正確、可閱讀 EPUB
4. Library 頁面隱藏上傳按鈕
5. Re-sync → idempotent（0 added, N unchanged）
6. 刪除 Calibre library → Book records 清除、EPUB 不刪
7. Sync 中刪除 library → sync abort

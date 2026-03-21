# Homepage Redesign & My Books Page

**日期**：2026-03
**狀態**：✅ 已完成

---

## 變更摘要

### 1. 修正 Recently Added 排序
- 首頁「Recently Added」原本用 `created_at` 排序，Calibre 同步的書會按匯入時間而非原始加入時間顯示
- 改用 `sort: "added_at"`，後端已有 `coalesce(calibre_added_at, created_at)` 邏輯
- 前端 client-side merge sort 也改用 `calibre_added_at ?? created_at`
- `BookOut` schema 新增 `calibre_added_at` 欄位

### 2. 新增 `GET /api/books/me` 後端 endpoint
- 查詢使用者有互動記錄的書籍（跨所有 library）
- 參數：`status`（reading status filter）、`favorite`（boolean）、`sort`、`order`、`limit`、`offset`
- 排序支援：`last_read_at`（從 JSONB 取值）、`updated_at`、`display_title`
- 透過 subquery 檢查 library 存取權限，避免 `DISTINCT ON` 與 `ORDER BY` 衝突
- 回傳 `PaginatedBooksWithInteraction`，包含 `reading_status`、`is_favorite`、`reading_percentage`、`last_read_at`

### 3. 首頁新增「Continue Reading」區塊
- 位於 Hero 與 Reading Activity Heatmap 之間
- 水平捲動列，顯示 `currently_reading` 狀態的書，按 `last_read_at` desc 排序
- 每張卡片顯示封面 + 書名 + 進度條（百分比）
- 點擊直接進入閱讀器 `/books/{id}/read`
- 沒有正在閱讀的書時整個區塊隱藏

### 4. 新增 `/my-books` 頁面
- Tab 切換：Currently Reading / Want to Read / Read / Did Not Finish / Favorites
- Tab 狀態存在 URL `?tab=` 參數
- 使用 `BookGrid` 元件顯示

### 5. Navbar 新增 "My Books"
- 位於 Home 和 Libraries 之間

## 關鍵決策

### Favorites 保持獨立，不併入書櫃
- Favorite 是 `UserBookInteraction.is_favorite` boolean，一鍵切換
- 書櫃是獨立的 `Bookshelf` + `BookshelfBook` 表，有排序功能
- 合併會增加不必要的操作複雜度
- 缺的只是「查看所有 favorites」的入口，由 `/my-books?tab=favorites` 解決

## 修改的檔案

### Backend
- `backend/app/schemas/book.py` — 新增 `BookWithInteractionOut`、`PaginatedBooksWithInteraction`；`BookOut` 加 `calibre_added_at`
- `backend/app/routers/books.py` — 新增 `GET /me` endpoint

### Frontend
- `frontend/src/lib/types.ts` — 新增 `BookWithInteractionOut`、`PaginatedBooksWithInteraction`；`BookOut` 加 `calibre_added_at`
- `frontend/src/lib/api/books.ts` — 新增 `getMyBooks()` 方法
- `frontend/src/routes/+page.svelte` — 新增 Continue Reading 區塊；修正 Recently Added 排序
- `frontend/src/routes/my-books/+page.svelte` — 新頁面
- `frontend/src/lib/components/Navbar.svelte` — 加 "My Books" 連結

## 踩過的坑

1. **PostgreSQL DISTINCT ON 必須匹配 ORDER BY** — 原本用 `distinct(Book.id)` 搭配 `order_by(last_read_at)`，PostgreSQL 要求 `DISTINCT ON` 表達式必須是 `ORDER BY` 的前綴。改用 subquery 先取可存取的 book_id，主查詢只 join `Book` + `UserBookInteraction`（1:1）避免重複
2. **封面圖片路徑** — 用了 `/api/books/{id}/cover`（需 auth），但 `<img>` 標籤不會帶 Bearer token。應該用 `/covers/{id}.jpg`（nginx 靜態服務）
3. **百分比計算** — `reading_progress.percentage` 已經是 0-100，不需要再乘以 100

# BeePub — agents/ 目錄索引

本目錄供 AI 協作使用，包含專案規劃文件和 log 記錄。

## Context
建立自架電子書管理系統，支援多人使用、多虛擬圖書館、線上閱讀、螢光筆、metadata 爬蟲、閱讀統計。
部署方式：Docker Compose on NAS。

## 需求
- 帳密登入，首個注冊使用者自動成為管理員
- 多人，管理員控制圖書館存取（public / private + 白名單）
- 無 DRM epub
- 新書上傳後自動觸發 metadata 爬取
- 閱讀狀態追蹤（want_to_read / currently_reading / read / did_not_finish）+ 開始/完成日期
- 每本書筆記（markdown）
- 閱讀時間統計（GitHub-style 熱力圖），自動偵測閱讀 session 累積秒數
- 自動閱讀狀態：讀 2 分鐘後自動設為 currently_reading，讀到最後一頁自動設為 read

## Tech Stack

| 層 | 技術 |
|----|------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 async, Alembic |
| Auth | python-jose (JWT HS256), bcrypt (SHA-256 prehash) |
| DB | PostgreSQL 16, asyncpg driver |
| Queue | Redis 7, redis-py |
| epub 解析 | ebooklib (vendored, 修改版), Pillow (封面) |
| Daemon 排程 | APScheduler 3 |
| 爬蟲 | httpx, BeautifulSoup4, rapidfuzz (模糊匹配) |
| Frontend | SvelteKit (@sveltejs/adapter-node), TailwindCSS |
| UI 元件 | shadcn-svelte |
| epub 閱讀器 | epubjs (forked, 本地 `frontend/src/lib/epubjs/`) |
| Icons | @lucide/svelte |

## 文件

| 檔案 | 內容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 目錄結構、Docker 服務、Auth 流程、Metadata Daemon |
| [DATABASE.md](DATABASE.md) | 資料庫 Schema（所有 table 定義） |
| [API.md](API.md) | Backend REST API 端點列表 |
| [FRONTEND.md](FRONTEND.md) | 前端路由、EPUB 閱讀器功能、epub.js fork 細節 |

## log 記錄

注意: 我們 008 以前的部分改動是在處理 hidden book (為了要精確顯示頁數) 的 bug，在 008 以後我們移除了 hidden book 放棄顯示精確頁數，改用百分比顯示。

| 檔案 | 問題 | 狀態 |
|------|------|------|
| [log/001-epub-page-restore.md](log/001-epub-page-restore.md) | EPUB 頁面還原 off-by-one | ✅ 已修復 |
| [log/002-epub-cover-extraction.md](log/002-epub-cover-extraction.md) | EPUB 3 封面抓取失敗 | ✅ 已修復 |
| [log/003-auth-session-expiry.md](log/003-auth-session-expiry.md) | Token 過期太快 + 未跳轉登入頁 | ✅ 已修復 |
| [log/004-epub-page-skip.md](log/004-epub-page-skip.md) | EPUB 翻頁跳頁 (sub-pixel scrollLeft) | ✅ 已修復 |
| [log/005-epub-prev-subpixel-shift.md](log/005-epub-prev-subpixel-shift.md) | EPUB prev() section 開頭卡住並平移 | ✅ 已修復 |
| [log/006-epub-rtl-footnote-and-vertical-restore.md](log/006-epub-rtl-footnote-and-vertical-restore.md) | RTL 註腳 + 直書頁面還原 | ✅ 已修復 |
| [log/007-mobile-safari-and-book-detail-actions.md](log/007-mobile-safari-and-book-detail-actions.md) | Mobile UX + Safari 問題 | ✅ 已修復 |
| [log/008-remove-hidden-book-percentage-only.md](log/008-remove-hidden-book-percentage-only.md) | 移除 hidden book，改百分比顯示 | ✅ 已完成 |
| [log/009-mobile-rtl-vertical-split-pages.md](log/009-mobile-rtl-vertical-split-pages.md) | 在手機板（螢幕較小）閱讀某些 **RTL 直排 EPUB** 時，畫面會出現裂頁 | ✅ 已修復 |
| [log/010-ios-custom-text-selection.md](log/010-ios-custom-text-selection.md) | iOS PWA 自訂文字選取（取代原生 UI） | ✅ 已修復 |
| [log/011-illustration-overlay-and-highlight-rect-dedup.md](log/011-illustration-overlay-and-highlight-rect-dedup.md) | Illustration 改為文字漸層標記 + getClientRects 矩形去重 | ✅ 已修復 |
| [log/012-epub-cover-extraction-broken-import.md](log/012-epub-cover-extraction-broken-import.md) | ebooklib import 壞掉導致封面抓取失敗 + SVG cover 支援 | ✅ 已修復 |
| [log/013-calibre-import.md](log/013-calibre-import.md) | Calibre library read-only import 整合 | ✅ 已完成 |
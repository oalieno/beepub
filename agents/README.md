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
| Queue | Redis 7, Celery (redis broker) |
| epub 解析 | ebooklib (vendored, 修改版), Pillow (封面) |
| 任務隊列 | Celery (prefork worker + beat scheduler) |
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
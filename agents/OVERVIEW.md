# BeePub 專案概述

## Context
建立自架電子書管理系統，支援多人使用、多虛擬圖書館、線上閱讀、螢光筆、metadata 爬蟲。
部署方式：Docker Compose on NAS。

## 需求
- 帳密登入，首個注冊使用者自動成為管理員
- 多人，管理員控制圖書館存取（public / private + 白名單）
- 無 DRM epub
- 新書上傳後自動觸發 metadata 爬取

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

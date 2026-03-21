# 020 — metadata-daemon → Celery worker refactor

## 背景
原本 metadata-daemon 是獨立 Python 服務，用自製 Redis BLPOP loop + APScheduler。
新增 word count 功能後出現兩套 worker（backend lifespan + daemon），架構重複且自製 queue 缺乏 retry/monitoring。

## 改動

### 刪除
- `metadata-daemon/` 整個目錄（Dockerfile, daemon/, tests/, pyproject.toml, uv.lock）
- `backend/app/services/metadata_queue.py`（舊的 Redis push helper）

### 新增
- `backend/app/celeryapp.py` — Celery app 設定，Redis broker，beat schedule
- `backend/app/tasks/metadata.py` — fetch_metadata + check_and_schedule_refresh
- `backend/app/tasks/wordcount.py` — compute_word_count（解析 EPUB 計算字數）
- `backend/app/services/epub_text.py` — EPUB 文字提取工具
- `backend/app/services/metadata_sources/` — 從 daemon 搬來的 base, goodreads, readmoo
- `backend/tests/` — 從 daemon 搬來的測試
- `backend/alembic/versions/009_add_word_count.py` — books 表新增 word_count 欄位

### 修改
- `backend/app/database.py` — 新增 `create_task_session()`，為 Celery task 建立獨立 async engine
- `backend/app/models/book.py` — 新增 word_count 欄位
- `backend/app/schemas/book.py` — BookResponse 新增 word_count
- `backend/app/routers/books.py` — 改用 `compute_word_count.delay()` + `fetch_metadata.delay()`
- `backend/app/routers/admin.py` — Calibre sync 改用 Celery tasks
- `backend/app/services/calibre.py` — sync 後觸發 word count task
- `docker-compose.yml` — 移除 metadata-daemon，新增 worker + beat 服務
- `docker-compose.dev.yml` — 同步更新
- Frontend: book detail 顯示 word count，types.ts 新增欄位

### 關鍵設計
- Celery worker 是 sync (prefork)，task 內用 `asyncio.run()` + `create_task_session()` 避免 asyncpg 跨 event loop 衝突
- word_count 異步計算：上傳/sync 時推 task，前端 null 則不顯示
- beat schedule 取代 APScheduler，每小時檢查 metadata refresh

## 狀態
✅ 已完成

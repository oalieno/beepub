# BeePub — agents/ 目錄索引

本目錄供 AI 協作使用，包含專案規劃文件和 debug 記錄。

## 文件

| 檔案 | 內容 |
|------|------|
| [OVERVIEW.md](OVERVIEW.md) | 專案概述、需求、Tech Stack、實作順序 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 目錄結構、Docker 服務、Auth 流程、Metadata Daemon |
| [DATABASE.md](DATABASE.md) | 資料庫 Schema（所有 table 定義） |
| [API.md](API.md) | Backend REST API 端點列表 |
| [FRONTEND.md](FRONTEND.md) | 前端路由、EPUB 閱讀器功能、epub.js fork 細節 |

## Debug 記錄

| 檔案 | 問題 | 狀態 |
|------|------|------|
| [debug/001-epub-page-restore.md](debug/001-epub-page-restore.md) | EPUB 頁面還原 off-by-one | ✅ 已修復 |
| [debug/002-epub-cover-extraction.md](debug/002-epub-cover-extraction.md) | EPUB 3 封面抓取失敗 | ✅ 已修復 |
| [debug/003-auth-session-expiry.md](debug/003-auth-session-expiry.md) | Token 過期太快 + 未跳轉登入頁 | ✅ 已修復 |
| [debug/004-epub-page-skip.md](debug/004-epub-page-skip.md) | EPUB 翻頁跳頁 (sub-pixel scrollLeft) | ✅ 已修復 |
| [debug/005-epub-prev-subpixel-shift.md](debug/005-epub-prev-subpixel-shift.md) | EPUB prev() section 開頭卡住並平移 | ✅ 已修復 |
| [debug/006-epub-rtl-footnote-and-vertical-restore.md](debug/006-epub-rtl-footnote-and-vertical-restore.md) | RTL 註腳 + 直書頁面還原 | ✅ 已修復 |
| [debug/007-mobile-safari-and-book-detail-actions.md](debug/007-mobile-safari-and-book-detail-actions.md) | Mobile UX + Safari 問題 | ✅ 已修復 |
| [debug/008-remove-hidden-book-percentage-only.md](debug/008-remove-hidden-book-percentage-only.md) | 移除 hidden book，改百分比顯示 | ✅ 已完成 |
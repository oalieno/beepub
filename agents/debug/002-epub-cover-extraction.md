# Debug: EPUB 封面抓取

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `backend/app/vendor/ebooklib/epub.py`
- `backend/app/services/epub_parser.py`

---

## 問題描述

EPUB 3 格式書籍的封面無法正確識別，fallback 到第一張圖片（通常不是封面）。

## 根因

ebooklib 在 parse manifest 時，image items 的 `properties` 屬性（`cover-image`）有讀取但未賦值給物件。另外 `EpubCover` 的 `get_type()` 回傳 `ITEM_COVER` 而非 `ITEM_IMAGE`，導致類型判斷不一致。

## 修復

1. 將 ebooklib vendor 到 `backend/app/vendor/ebooklib/`，在 `epub.py` 加入 `ei.properties = properties`
2. `epub_parser.py` Method 2 改用 `book.get_items()` 全掃描配合 `properties` 欄位判斷

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

---

## 補充案例（OPF2：`meta name="cover"` + `guide`）

**現象**：某些 EPUB 2 雖然有

```xml
<meta name="cover" content="cover-image"/>
<item id="cover-image" href="html/docimages/cover.jpg" media-type="image/jpeg"/>
<reference type="cover" href="html/000_cover.html"/>
```

但 `item` 沒有 `properties="cover-image"`，且 `guide` 先指向 html 文件，導致舊策略不一定能穩定拿到圖片。

**補強修復（`epub_parser.py`）**：

1. 新增 OPF `meta` 掃描：若 `get_metadata("OPF", "cover")` 無結果，改掃 `get_metadata("OPF", "meta")` 內 `name=cover` 取 `content` 當 id。
2. 新增 `guide type="cover"` 支援：若指向 html，解析第一個 `<img src>` 再回找對應圖片 item。
3. 新增 cover html fallback：掃描 id/href 含 `cover` 的 document，解析第一張圖。
4. image 判斷統一為 media-type `image/*` 或 `ITEM_IMAGE/ITEM_COVER`。

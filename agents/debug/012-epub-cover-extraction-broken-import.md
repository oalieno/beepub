# Debug: EPUB 封面抓取失敗（ebooklib import 壞掉 + SVG cover）

**日期**：2026-03
**狀態**：✅ 已修復
**影響檔案**：
- `backend/app/vendor/ebooklib/epub.py`
- `backend/app/services/epub_parser.py`

---

## 問題描述

某些 EPUB 3 書籍（如《千年鬼》）的封面無法抓取，`extract_cover()` 回傳 `False`。該書的 manifest 有 `properties="cover-image"` 標記在正確的圖片上，但提取仍然失敗。

## 根因

### Bug 1：`ebooklib` import 壞掉（主因）

`epub.py` 第 36 行原本是：
```python
from . import __init__ as ebooklib
```

在 Python 3 中，`__init__` 被解析為 module 的 `__init__` method-wrapper，而非 `__init__.py` 模組。導致所有 `ebooklib.ITEM_*` 常數引用都會拋 `AttributeError`。

**影響鏈**：
1. `extract_cover()` Method 1b 呼叫 `_is_image_item()` 判斷 guide 指向的 cover.xhtml
2. `media_type` 不是 image → 進入 `item.get_type()` 分支
3. `EpubHtml.get_type()` 回傳 `ebooklib.ITEM_DOCUMENT` → **AttributeError**
4. 例外被外層 `except Exception: return False` 吞掉
5. Method 2（properties="cover-image"）根本沒機會執行

### Bug 2：SVG `<image>` 不支援（次因）

日文/中文 EPUB 的封面頁（如 `p-cover.xhtml`）常用 SVG 包裝圖片：
```html
<svg><image xlink:href="image/10.jpg"/></svg>
```

`_first_img_src_from_html()` 只匹配 `<img src="...">` regex，不支援 SVG `<image>` 標籤。即使 Bug 1 修好，Method 1b 仍會因為找不到 `<img>` 而跳過，需要靠 Method 2 兜底。

## 修復

### Fix 1：`epub.py` import

```python
# Before (broken)
from . import __init__ as ebooklib

# After (correct)
import sys as _sys
ebooklib = _sys.modules[__package__]
```

### Fix 2：`epub_parser.py` SVG 支援

在 `_first_img_src_from_html()` 增加 SVG `<image>` regex：
```python
match = re.search(r"<image[^>]+(?:xlink:)?href=[\"']([^\"']+)[\"']", text, re.IGNORECASE)
```

## 驗證

建立最小 EPUB 測試：
- cover.xhtml 使用 SVG `<image>` 引用 image/10.jpg（藍色）
- image/0.jpg（紅色）作為干擾
- 修復後 `extract_cover()` 正確抓到藍色圖片（image/10.jpg）

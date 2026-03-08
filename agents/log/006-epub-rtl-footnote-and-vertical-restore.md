# Debug: RTL Footnote Popup Link + Vertical Page Restore

**日期**：2026-03
**狀態**：✅ 已修復（RTL 直式書）
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`
- `frontend/src/lib/components/reader/EpubReader.svelte`

---

## 問題摘要

1. **頁尾 footnote 回跳後排版壞掉**
2. **退出再進來頁碼錯位**（例如 100 頁回來變 94 頁）
3. **footnote popup 內數字連結點擊變 404**（開到前端 route）
4. **RTL 直排數字可讀性差**（數字方向不對）

## 代表性 log（節錄）

```text
[moveTo] offset.left: 432.21875 delta: 2519 page (0-idx): 0 distX: 0 scrollWidth: 2519
[scrollTo] x:0 y:12595 silent:true scrollLeft:0->0
[scrolledLocation] ... vertical: true rtl: true ... currPage: 11 endPage: 12 totalPages: 17
```

```text
[moveTo] offset.left: 2325.479... delta: 1238 page (0-idx): 1 distX: 1238
[scrollTo] x:-43 y:6190 ...
[relocated] ... secPage: 6 / 17 ... absolutePage: 94
```

## 根因

### A. axis=vertical 路徑沒有被 page restore 的修正覆蓋
先前 page restore 主要是 horizontal 想定（`delta/scrollWidth/distX`），但這本書實際是 `isPaginated + axis=vertical`，應該使用 `height/scrollHeight/distY`。

### B. `moveTo()` 在 vertical paginated 還套用了 horizontal RTL 的 X 軸補償
導致 `x:-43` 這種異常偏移，進一步把位置拉回錯頁（94）。

### C. footnote popup 內的 `<a href>` 是 EPUB 內相對路徑
直接在 app DOM 點擊會被 browser 以目前 SPA route 解譯，導向前端 `/books/...` 路由而 404。

## 修復

### 1) `scrollToPageIndex(pageIndex)` 改為 axis-aware
- vertical: `pageStep = layout.height`，檢查 `scrollHeight`，`scrollTo(0, distY)`
- horizontal: 保留 `layout.delta` 與 RTL scrollType 的 distX 轉換

### 2) `moveTo(offset, width)` 改為 axis-aware
- vertical paginated 只計算/套用 `distY`
- horizontal paginated 才使用 `distX` 與 RTL X 軸修正

### 3) footnote popup 連結改由 reader 接手
- 新增 `normalizeFootnoteHref()`：以 footnote 來源章節路徑解析 relative href
- 新增 `handleFootnoteContentClick()`：攔截 popup 內 `<a>`，改用 `rendition.display()`
- 避免直接讓瀏覽器跳轉到前端 route（404）

### 4) RTL 直排數字可讀性
- 針對 popup 內連結/上標加：
  - `text-orientation: upright`
  - `text-combine-upright: all`

## 清理

- 移除 `rendition.on('link')` 中多層 `setTimeout(...display...)` 的暫時包裝
- 保留主要 `console.log` 供後續 debug

## 備註

仍保留 `footnoteOpenedThisClick` 的 `setTimeout(..., 0)`：此段用來避免同一 click event cycle 被外層 click handler 立即關閉 popup，屬必要保護。

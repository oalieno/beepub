# Debug: Mixed-layout EPUB per-item pre-paginated 與 expand loop

**日期**：2026-03
**狀態**：✅ 已修復
**影響檔案**：
- `frontend/src/lib/epubjs/layout.js`
- `frontend/src/lib/epubjs/managers/views/iframe.js`

---

## 問題摘要

兩個互相關聯的問題：

### 問題 A：Mixed-layout EPUB 的 pre-paginated 頁面觸發 expand loop

部分 RTL EPUB 是 **mixed-layout**：全局 metadata 沒有 `rendition:layout`（預設 reflowable），但個別 spine item 標記 `rendition:layout-pre-paginated`（封面、插圖頁等）。

```xml
<itemref idref="p-cover" properties="rendition:layout-pre-paginated rendition:spread-none"/>
```

epub.js 只看全局 metadata（`this.name === "pre-paginated"`），忽略 per-item override → 所有 section 都走 reflowable 的 `columns()` 路徑 → 封面 SVG 在 CSS columns 下觸發 expand() 無限迴圈 → iframe 膨脹到數百頁空白。

### 問題 B：非 pre-paginated 頁面也有 expand loop

千年鬼的 `p-colophon`（版權頁）只有 `page-spread-right` 屬性，沒有 `rendition:layout-pre-paginated`，但有 `class="hltr"`（水平 LTR）+ 特殊 CSS → 觸發同樣的 expand loop（textWidth 每次增加恰好 1 個 pageWidth，永不收斂）。

---

## 根因分析

### 問題 A 根因

`layout.js` 的 `format()` 和 `iframe.js` 的 `size()`/`expand()` 只檢查全局 layout name：

```javascript
if (this.layout.name === "pre-paginated") { ... }
```

`section.js` 有 `reconcileLayoutSettings()` 方法可以解析 per-item properties，但從未被呼叫（dead code）。

### 問題 B 根因

`p-colophon` 不是 pre-paginated，是真正的 reflowable 文字頁面，但它的 CSS（`style0.css` / `style6.css`）在 CSS columns 下會導致 `textWidth()` 每次 expand 增加恰好 1 個 `pageWidth`，永不收斂。這跟 log 016 的 p-titlepage 是同一個模式。

---

## 修復方案

### ✅ 修復 A：Per-item pre-paginated 偵測

在三個地方加入 per-item pre-paginated 檢查：

**1. `layout.js` format() — 跳過 columns()，用 flex 置中**

```javascript
var isPrePaginated = this.name === "pre-paginated" ||
  (section && section.properties &&
   section.properties.includes("rendition:layout-pre-paginated"));

if (this.name === "pre-paginated") {
  formating = contents.fit(this.columnWidth, this.height, section);
} else if (isPrePaginated) {
  // 用 class + injected stylesheet，讓 styles 在 theme override 後仍生效
  contents.layoutStyle("paginated");
  contents.width(this.width);
  contents.height(this.height);
  contents.overflow("hidden");
  contents.addClass("beepub-pre-paginated");
  contents.addStylesheetCss(
    "body.beepub-pre-paginated { padding: 32px !important; display: flex !important; ... } " +
    "body.beepub-pre-paginated svg, body.beepub-pre-paginated img { max-width: 100% !important; ... }",
    "beepub-pre-paginated"
  );
} else if (this._flow === "paginated") {
  formating = contents.columns(...);
}
```

**2. `iframe.js` size() — 鎖定兩軸**

```javascript
var isPrePaginated = this.layout.name === "pre-paginated" ||
  (this.section && this.section.properties &&
   this.section.properties.includes("rendition:layout-pre-paginated"));

if (isPrePaginated) {
  this.lock("both", width, height);
}
```

**3. `iframe.js` expand() — 固定尺寸不擴展**

```javascript
if (isPrePaginated) {
  width = this.layout.columnWidth;
  height = this.layout.height;
}
```

**4. `iframe.js` EXPAND/RESIZE/setLayout handlers — 傳 section 參數**

原本 `this.layout.format(this.contents)` 不傳 section，重新 format 時 per-item check 失敗。改為 `this.layout.format(this.contents, this.section, this.axis)`。

### ✅ 修復 B：Expand 發散偵測

在 `iframe.js` expand() 的水平分支加入發散偵測：

```javascript
// 偵測 textWidth 連續增加 ≈ 1 pageWidth 的發散模式
if (this._prevExpandWidth !== undefined) {
  var growth = width - this._prevExpandWidth;
  if (growth >= this.layout.pageWidth * 0.9 &&
      growth <= this.layout.pageWidth * 1.1) {
    this._divergeCount = (this._divergeCount || 0) + 1;
    if (this._divergeCount >= 2) {
      width = this._prevExpandWidth; // 停止擴展
    }
  } else {
    this._divergeCount = 0;
  }
}
this._prevExpandWidth = width;
```

每次 `render()` 重設 `_prevExpandWidth` 和 `_divergeCount`。

---

## 踩過的坑

### ❌ 用 `contents.fit()` 處理 per-item pre-paginated

`fit()` 讀 viewport meta（`<meta name="viewport" content="width=1457, height=2048">`），按 viewport 大小縮放整個頁面。封面變得很小（scale 0.247）。

### ❌ 用 `contents.size()` 處理 per-item pre-paginated

`size()` 會呼叫 `layoutStyle("scrolling")`，錯誤設定排版模式。

### ❌ 用 `contents.css()` 設定 padding

`format()` 在 theme hooks 之前執行。Theme 設定 `body { padding: 2rem !important }` 會覆蓋 format 的 inline styles（兩者都是 !important，但 theme 後執行）。

**解法**：用 `addClass()` + `addStylesheetCss()` 注入帶有 class selector 的 CSS rule。`body.beepub-pre-paginated`（specificity 0-1-1）贏過 theme 的 `body`（specificity 0-0-1）。

### ❌ 用 `rem` 單位設定 padding

千年鬼的 `style0.css` 設定 `html, body { font-size: 0; }`。`rem` 相對 html 的 font-size → `2rem = 2 * 0 = 0px`。不同 EPUB 有不同的 CSS，必須用 `px` 單位。

### ❌ 對 SVG 設定 `width: auto; height: auto`

SVG 的 `width="100%" height="100%"`（HTML attributes）是相對值。用 `auto` 覆蓋後，SVG 沒有 intrinsic size → 塌縮成 0×0。只用 `max-width/max-height` 限制就好，不要改 width/height。

### ❌ 之前的全域發散偵測（textWidth >= prevTextWidth → 停）

太激進，正常 reflow 也會讓 textWidth 微幅增長（幾 px），導致 LTR 長章節後半段被截斷。

**這次的偵測更精準**：只在增長量 ≈ pageWidth（±10%）且連續 2 次時才攔截。正常 reflow 的增長是幾 px，遠小於 pageWidth（393px），不會被影響。

---

## 關鍵教訓

1. **epub.js 的 `format()` 在 theme hooks 之前執行** — 用 inline styles 設 padding 會被 theme 覆蓋。用 class + stylesheet injection 提高 specificity 才行。
2. **不要用 `rem` 單位** — EPUB 的 CSS 不可預測，有些書會設 `html { font-size: 0 }`。用 `px`。
3. **SVG 不能 `width: auto`** — SVG 的 percentage width 是相對值，改 auto 會變 0×0。只用 `max-width` 限制。
4. **發散偵測要精準** — 偵測特定模式（增長量 ≈ pageWidth），不要偵測任何增長。
5. **`format()` 在多處被呼叫** — render chain 傳 section，但 EXPAND/RESIZE/setLayout handlers 原本不傳。改了 format 的行為後，這些 handler 也要同步更新。
6. **`section.properties` 是 `Array<string>`** — 由 `packaging.js` 從 itemref 的 properties attribute 用 `split(" ")` 解析。用 `.includes()` 檢查。

---

## 相關檔案

- `frontend/src/lib/epubjs/layout.js` — format() per-item pre-paginated 分支
- `frontend/src/lib/epubjs/managers/views/iframe.js` — size()/expand() per-item 偵測 + 發散偵測
- `frontend/src/lib/epubjs/managers/default/index.js` — next() scroll-didn't-move 防護（仍保留）
- `frontend/src/lib/epubjs/contents.js` — fit()/columns()/size()/css()/addClass()/addStylesheetCss()
- `frontend/src/lib/epubjs/packaging.js` — parseSpine() 解析 itemref properties
- `agents/log/016-rtl-titlepage-blank-pages.md` — 早期 expand loop 修法（scroll-didn't-move）

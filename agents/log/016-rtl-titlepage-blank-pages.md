# Debug: RTL 直排書封面翻頁後大量空白頁

**日期**：2026-03
**狀態**：✅ 已修復
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`

---

## 問題摘要

iPhone PWA 閱讀 RTL 直排日文 EPUB（千年鬼），從封面往後翻，翻 2 頁後出現大量空白頁（8+ 頁），點擊有反應（paginatedLocation log 持續輸出且 start/end 值遞增）但畫面全白。

---

## 根因分析

### expand() 無限迴圈

`p-titlepage.xhtml` 的 HTML 標記為 `class="hltr"`（水平 LTR），但內容包含 vertical-rl 樣式的子元素。epub.js 偵測為水平軸 → 套用 CSS columns（`column-width: 509px`）。

`iframe.js` 的 `expand()` 進入無限迴圈：
1. `textWidth()` 透過 `range.getBoundingClientRect().width` 測量內容寬度
2. 內容寬度 = N 頁 → iframe 擴展到 N 頁
3. `ResizeObserver` 觸發 → `resizeCheck()` → `expand()` 再次執行
4. 更寬的 iframe 導致 CSS columns 重新分配 → `textWidth` 每次增加恰好 1 個 pageWidth（393px）
5. 永遠不會收斂 → iframe 膨脹到數百頁的空白空間

### 翻頁卡在空白區

`next()` 中水平 RTL 的邊界偵測使用 `scrollLeft >= delta/2`。膨脹的 view 有巨大的 scrollWidth，`scrollLeft` 始終高於閾值 → `scrollBy()` 在空白區域中捲動，而非載入下一個 section。

---

## 修復方案

### ✅ 最終方案：next() scroll-didn't-move 防護

在 `default/index.js` 的 `next()` 中，對所有 3 個水平分支（LTR、RTL default、RTL non-default）加入偵測：`scrollBy()` 之後檢查 `scrollLeft` 是否真的改變了。如果沒有 → view 已耗盡 → 載入下一個 section。

```javascript
// 以 LTR 分支為例
let before = this.container.scrollLeft;
this.scrollBy(this.layout.delta, 0, true);
if (this.container.scrollLeft === before) {
  next = this.views.last().section.next();
}
```

同樣邏輯套用到 RTL default 和 RTL non-default 分支。

---

## 嘗試過但失敗的方案

### ❌ expand() 循環次數上限（cap at N）

在 `iframe.js` 的 `expand()` 加入計數器，超過 N 次就停止。

- cap 10：title page 仍有 ~8 頁空白
- cap 3：空白頁減少但仍有 2-3 頁

### ❌ expand() 發散偵測（divergence detection）

追蹤 `_prevTextWidth`，若 `textWidth >= prevTextWidth` 則停止擴展。

- 對 title page 有效（第 2 次循環即停止）
- **但破壞了 LTR 長章節**：合法的內容 reflow 也會讓 textWidth 微幅增長，導致章節後半段被截斷
- 加上「僅對小內容生效」的條件（`prevTextWidth <= pageWidth * 3`）仍不夠穩定

### 關鍵教訓

1. **不要動 expand()**：它是一個脆弱的收斂迴圈，修改它會對所有書籍造成回歸
2. **在導航層（next/prev）修復**，而非在尺寸計算層（expand/reframe）
3. **`this.views.length` 是 property 不是 method**：呼叫 `this.views.length()` 會靜默回傳 undefined/拋錯，導致所有書籍的顯示流程崩潰（全白頁面 + 空白 TOC）
4. 每次修改都要用多種書籍測試（LTR、RTL、不同內容長度）

---

## 相關檔案

- `frontend/src/lib/epubjs/managers/views/iframe.js` — expand()/reframe() 循環
- `frontend/src/lib/epubjs/managers/default/index.js` — next()/prev() 導航
- `frontend/src/lib/epubjs/contents.js` — textWidth()/textHeight()/resizeCheck()
- `frontend/src/lib/epubjs/layout.js` — layout.format() 套用 CSS columns
- `agents/log/009-mobile-rtl-vertical-split-pages.md` — 早期 RTL 除錯筆記

# Debug: Mobile RTL 直排書裂頁 + re-enter 定位不準（完整修復紀錄）

**日期**：2026-03
**狀態**：✅ 已修復（經歷多輪迭代）
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`
- `frontend/src/lib/components/reader/EpubReader.svelte`

---

## 問題摘要

在手機板（螢幕較小）閱讀 **RTL 直排 EPUB** 時，出現多種裂頁與定位問題：

1. **Re-enter 裂頁**：重新進入書籍時，畫面停在頁與頁的中間（同時看到兩頁各一半）
2. **Re-enter 跳頁**：恢復進度後停在錯誤的頁碼
3. **章節跳轉裂頁**：從章節二往回翻到章節一最後幾頁時出現裂頁
4. **連續翻頁累積偏移**：同章連翻很多頁後，偏差逐漸累積導致裂頁

這些問題互相糾纏，修好一個常常會讓另一個復發（打地鼠現象）。

---

## 根因分析（共 6 個獨立問題）

### 根因 1: 浮點數 pageStep 造成累積偏移

`getPageStep()` 在 vertical 模式下使用 `getBoundingClientRect().height`，會回傳浮點數（如 `851.3359375`）。
連續翻頁時 `pageIndex * pageStep` 的浮點數乘法會累積誤差，導致 scroll 位置逐漸偏離頁面邊界。

**症狀**：連續翻很多頁後出現裂頁，且越翻越嚴重。

**修復**：`getPageStep()` 在 vertical 模式下加 `Math.floor(raw)` 取整。

```javascript
// index.js getPageStep() — vertical 路徑
const raw = (bounds && bounds.height) || ... || 0;
return Math.floor(raw); // 防止浮點數累積偏移
```

### 根因 2: `next()`/`prev()` 使用相對 `scrollBy` 造成漂移

`next()` 和 `prev()` 原本用 `scrollBy(0, pageStep)` 做相對捲動。因為瀏覽器的 DPR snap（如 DPR=1.5 時 scrollTop 會被 snap 到 2/3 px 的倍數），每次 scrollBy 都會引入微小偏差。

**症狀**：連續翻頁時 scrollTop 逐漸偏離 page grid。

**修復**：改用 `scrollToPageIndex(targetPage)` 做絕對定位。

```javascript
// index.js next() — vertical paginated
const pageStep = this.getPageStep();
const currentPage = Math.round(this.container.scrollTop / pageStep);
const targetPage = currentPage + 1;
this.scrollToPageIndex(targetPage);
```

### 根因 3: `counter()` 的 prepend 補償未 snap 到 page grid

章節跳轉時 `prepend` 新內容後，`counter(bounds)` 用 `scrollBy(0, heightDelta)` 補償。
`heightDelta` 不一定是 pageStep 的整數倍，導致補償後 scrollTop 不在頁面邊界。

**症狀**：章節二往回翻到章節一最後幾頁時出現裂頁。

**修復**：`counter()` 改為計算補償後的目標頁碼，再 snap 到 page grid。

```javascript
// index.js counter() — vertical paginated
const targetTop = Math.max(0, Math.min(topBefore + delta, maxScrollable));
const targetPage = Math.max(0, Math.floor((targetTop + 1) / pageStep));
const snappedTop = targetPage * pageStep;
this.scrollTo(0, snappedTop, true);
```

### 根因 4: `prev()` 跨章節時缺少 scroll-to-last-page

Horizontal 模式的 `prev()` 在 prepend 後會 `scrollTo(scrollWidth - delta)` 跳到最後一頁。
Vertical 模式沒有對應邏輯，依賴 `counter()` 的補償，但補償結果可能不精確。

**症狀**：從章節二往回翻時到的不是章節一的最後一頁。

**修復**：為 vertical paginated 的 `prev()` 加入明確的 scroll-to-last-page。

```javascript
// index.js prev() — vertical paginated, after prepend
const pageStep = this.getPageStep();
const maxScroll = this.container.scrollHeight - pageStep;
const lastPage = Math.max(0, Math.floor((maxScroll + 1) / pageStep));
this.scrollToPageIndex(lastPage);
```

### 根因 5: `scrolledLocation()` 的 `Math.ceil` 被 sub-pixel noise 干擾

`scrolledLocation()` 用 `Math.ceil(startPos / stopPos)` 計算目前頁碼。
`startPos` 由 `getBoundingClientRect()` 計算，會帶入 ~0.003px 的 sub-pixel 雜訊。
在精確的頁面邊界上，`Math.ceil(66.0000035) = 67` 而非預期的 66，導致頁碼永遠虛高 +1。

**症狀**：
- 報告的頁碼比實際位置多 1
- save/restore round-trip 不一致（存 page 67，restore 到 page 66 的位置，但報告 page 68）

**修復**：vertical paginated 模式改用 `Math.round`（scroll 位置保證在整數 page 邊界，sub-pixel noise < 0.5）。

```javascript
// index.js scrolledLocation()
let currPage = vertical && this.isPaginated
    ? Math.round(startPos / stopPos)
    : Math.ceil(startPos / stopPos);
let endPage = vertical && this.isPaginated
    ? Math.round(endPos / stopPos)
    : Math.ceil(endPos / stopPos);
```

### 根因 6: pageStep 在 font/CSS load 前後不同

初始 render 時 container 高度可能是 871px（預設字型），font load 後變成 851px。
`section_page` 校正在 871 的 grid 上成功（`scrollToPageIndex(16)` → 16×871=13936），
但 font load 後 pageStep 變 851，13936 不在 851 的 grid 上（13936 % 851 = 320）→ 裂頁。

由於 `scrollToPageIndex` 已「成功」回傳 true，`_lastTargetPage` 被清除，`afterResized` 無法重試。

**症狀**：某些頁面 re-enter 出現裂頁，翻一頁就消失。

**修復**（三層防禦）：

1. **EpubReader.svelte**：vertical 模式不在初始 `scrollToPageIndex` 成功後清除 `_lastTargetPage`。
   讓 `afterResized` 在 font load 完成後以穩定的 pageStep 重新套用。

2. **index.js `afterResized()`**：加入 vertical paginated re-snap 邏輯。
   內容 resize 後若 `scrollTop % pageStep` 偏離 page grid 超過 2px，自動 snap 回最近的頁面。

3. **EpubReader.svelte `setTimeout`**：150ms 延遲後再做一次 re-snap 檢查。
   作為 `afterResized` 不觸發時的 fallback。

```javascript
// index.js afterResized() — re-snap
if (this.settings.axis === "vertical" && this.isPaginated) {
    const pageStep = this.getPageStep();
    if (pageStep > 0) {
        const scrollTop = this.container.scrollTop;
        const remainder = scrollTop % pageStep;
        if (remainder > 2 && pageStep - remainder > 2) {
            const currentPage = Math.round(scrollTop / pageStep);
            this.scrollTo(0, currentPage * pageStep, true);
        }
    }
}
```

---

## 額外修復：horizontal LTR 書的 re-enter 回歸

在修改 `_lastTargetPage` 邏輯時不小心引入回歸：horizontal 模式下即使 `scrollToPageIndex` 失敗
（`scrollWidth` 尚未完全展開），`_lastTargetPage` 也被清除，導致 `afterResized` 無法重試。

**修復**：加入 `ok &&` 條件檢查，只在成功時清除。

```javascript
// EpubReader.svelte — section_page 校正
const ok = mgr.scrollToPageIndex(targetPage);
// horizontal：成功才清除，失敗留給 afterResized 重試
// vertical：永遠不清除，留給 afterResized 以穩定 pageStep 重新套用
if (ok && mgr?.settings?.axis !== 'vertical') {
    mgr._lastTargetPage = null;
}
```

---

## 修改的檔案總結

### `frontend/src/lib/epubjs/managers/default/index.js`

| 函數 | 修改 |
|------|------|
| `getPageStep()` | vertical 模式取 `Math.floor()` 整數 |
| `next()` / `prev()` | vertical paginated 改用 `scrollToPageIndex` 絕對定位 |
| `prev()` | 加入 vertical paginated 的 scroll-to-last-page |
| `counter()` | vertical paginated 改為 snap to page grid |
| `scrolledLocation()` | vertical paginated 的 `currPage`/`endPage` 改用 `Math.round` |
| `afterResized()` | 加入 vertical paginated re-snap（`scrollTop % pageStep` 偏離時自動修正）|

### `frontend/src/lib/components/reader/EpubReader.svelte`

| 位置 | 修改 |
|------|------|
| section_page 校正 | 全模式啟用；vertical 不清 `_lastTargetPage`；horizontal 只在成功時清 |
| setTimeout snap | 從 `snap.snap(0)` 改為 vertical re-snap 檢查（150ms fallback）|

---

## 關鍵教訓

### 1. Sub-pixel 問題是一整個系列
與 debug 004、005 同源。DPR snap、`getBoundingClientRect` 浮點數、`scrollBy` 累積偏差
在 vertical paginated 模式下特別容易觸發，因為涉及 Y 軸大量 scroll 計算。

### 2. 「打地鼠」問題的解法是多層防禦
這次問題之所以反覆出現，是因為有 6 個獨立根因互相掩蓋：
- 修好 pageStep 浮點數 → 暴露 scrollBy 累積偏差
- 修好 scrollBy → 暴露 counter snap 問題
- 修好 counter → 暴露 Math.ceil sub-pixel inflation
- 修好 Math.ceil → 暴露 pageStep 在 font load 前後不同

必須全部修好才能穩定。逐一修復時要確保不引入回歸。

### 3. pageStep 在生命週期不同時間可能不同
初始 render 時 container 高度（如 871）與 font load 後的高度（如 851）不同。
任何在初始 render 時計算的 scroll 位置，在 font load 後都可能失效。
因此需要 `afterResized` re-snap 或延遲校正機制。

### 4. `_lastTargetPage` 是重要的 retry 機制
`scrollToPageIndex` 在 scrollWidth/scrollHeight 尚未完全展開時會失敗或用錯 pageStep。
`_lastTargetPage` 讓 `afterResized` 可以在 content 穩定後重試。
**不可在 scrollToPageIndex 失敗時清除它**（horizontal 回歸的教訓）。
**vertical 模式更不可清除**，因為 pageStep 本身可能在 font load 後改變。

### 5. restore 策略必須按 axis 區分
- **horizontal paginated**：`scrollToPageIndex` 成功即清除 `_lastTargetPage`，`afterResized` 做 fallback
- **vertical paginated**：`scrollToPageIndex` 不清除 `_lastTargetPage`，`afterResized` 做 re-snap，150ms setTimeout 做 fallback
- **scrolled**：不需要 page-based restore

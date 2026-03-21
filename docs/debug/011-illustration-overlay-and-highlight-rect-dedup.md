# Debug: Illustration 改為文字漸層標記 + Highlight/Illustration 矩形去重

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `frontend/src/lib/components/reader/EpubReader.svelte`
- `frontend/src/lib/epubjs/managers/views/iframe.js`

---

## 問題摘要

### 1) Illustration 從 icon 改為文字漸層標記

原本 AI 插圖完成後，會在 reader 外層浮動一個 icon，點擊打開插圖。
改為直接在對應文字上蓋上漸層背景（`linear-gradient(135deg, purple, blue, pink)` 各 30% opacity），
點擊該段文字一樣打開插圖 viewer。

### 2) getClientRects() 回傳異常大矩形

當 highlight 或 illustration 的文字範圍跨越多行時，`getClientRects()` 除了回傳每行的矩形，
還會回傳一個涵蓋多行的大矩形（aggregate bounding rect）。這導致畫面上出現一個異常的大色塊。

---

## 根因分析

### Illustration overlay

- 使用 `Range.getClientRects()` 取得文字矩形座標
- 在 iframe 內建立 `position:absolute` 的 overlay root（`div#beepub-illustration-overlay`）
- 每個矩形建立一個 `<button>` 覆蓋文字並套用漸層背景

### 矩形去重問題

`getClientRects()` 對跨多行 range 可能回傳：
- 第一行：部分寬度（從選取起點到行尾）
- 中間行：全行寬度
- 最後行：部分寬度（從行首到選取終點）
- **額外**：一個涵蓋所有行的大矩形（partially overlapping）

原本 `marks-pane` 的 `filteredRanges()` 只用 **完全包含（containment）** 來去重，
無法處理部分重疊的 aggregate rect。

### RTL 直排書漸層消失

- overlay root 繼承了 `writing-mode: vertical-rl`，導致定位異常
- viewport-based visibility 判斷在直排分欄模式下座標不正確，過濾掉所有 rect

---

## 最終修復

### Illustration overlay（EpubReader.svelte）

1. **新增函式**：
   - `ensureIllustrationOverlayRoot(contents)` — 在 iframe body 建立 overlay root
   - `updateIllustrationOverlays()` — 遍歷 illustrations，用 `getClientRects()` 畫漸層 button

2. **overlay root 樣式**：
   - `writing-mode: horizontal-tb` — 不繼承直排書的 vertical-rl
   - 尺寸用 `scrollWidth/scrollHeight` 覆蓋整個可捲動區域

3. **移除 viewport visibility 判斷** — 讓 iframe 的 `overflow:hidden` 自然裁切

4. **矩形去重（overlap-based）**：
   - 兩兩比較所有 rect
   - 計算重疊面積
   - 若重疊 > 較小 rect 面積的 50%，丟掉較大的那個

5. **舊 icon 邏輯移除** — 不再有外層浮動 icon

### Highlight SVG 去重（iframe.js）

- Monkey-patch `Highlight.prototype.filteredRanges`
- 套用同樣的 overlap-based 去重邏輯
- 取代原本 marks-pane 的 containment-only 去重

---

## 去重演算法

```js
// 兩兩比較 rect
for (let i = 0; i < rects.length; i++) {
  for (let j = i + 1; j < rects.length; j++) {
    const overlap_x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
    const overlap_y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
    const overlap_area = overlap_x * overlap_y;
    if (overlap_area > Math.min(areaA, areaB) * 0.5) {
      discard(larger_rect);
    }
  }
}
```

---

## 驗證結果

- ✅ 橫排書：跨多行 illustration/highlight 不再出現異常大矩形
- ✅ RTL 直排書：漸層背景正常顯示
- ✅ 點擊漸層文字可正常打開插圖 viewer
- ✅ 翻頁後 overlay 跟隨文字位置更新

---

## 備註

- Illustration overlay 刻意不走 epub.js 內建的 annotation SVG，避免改動 fork 底層的 marks-pane 渲染
- Highlight 的 SVG 去重則透過 prototype patch 處理，不需修改 npm 套件原始碼
- 去重閾值 50% 在實測中表現穩定，既能過濾 aggregate rect，又不誤殺相鄰行的正常 rect

# Debug: EPUB prev() 在 section 開頭卡住並平移 (Sub-pixel Shift)

**日期**：2026-03
**狀態**：✅ 已修復
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`

---

## 問題描述

往前翻頁到某個 section 的第 1 頁後，再按 prev 不會跳到上一個 section，而是停在同一頁但內容往右平移幾個 pixel。每個 section 的第一頁都會出現。

**重現步驟**：在任意 section 的第 2 頁 → prev 到第 1 頁 → 再 prev → 還是第 1 頁但畫面右移

## 調查過程

### Phase 1: Console log 觀察

```
[next]  scrollLeft: 0 → scrollBy(+1237) → 1237.333   (browser snaps to column boundary)
[prev]  scrollLeft: 1237.333 → scrollBy(-1237) → 0.666
[prev]  scrollLeft: 0.666 → left > 0 is TRUE → scrollBy(-1237) → 0  (平移而非換 section)
```

sub-pixel 原因：DPR=1.5 時，1237 CSS px × 1.5 = 1855.5 物理 px → 進位到 1856 → 1856/1.5 = 1237.333 CSS px。

### Phase 2: Math.round / Math.floor 不夠

- `Math.round(0.666)` = 1 → `1 > 0` 仍為 true ❌
- `Math.floor(0.666)` = 0 → 看似 OK

但翻更多頁後誤差會累積：
```
Page 3 → 2: scrollLeft = 2476 → scrollBy(-1237) → 1239.333
Page 2 → 1: scrollLeft = 1239.333 → scrollBy(-1237) → 2.666
```
`Math.floor(2.666)` = 2 → `2 > 0` 仍為 true ❌

### Phase 3: 最終修復 — 閾值判斷

**舊邏輯**（對 sub-pixel 敏感）：
```javascript
left = this.container.scrollLeft;
if (left > 0) {  // 2.666 > 0 → true → scrollBy 而非換 section
```

**新邏輯**（robust）：
```javascript
left = this.container.scrollLeft;
if (left >= this.layout.delta / 2) {  // 2.666 >= 618.5 → false → 正確換 section
```

**為什麼正確**：
- 第一頁的 scrollLeft 永遠 ≈ 0（加上幾 px 的累積誤差）
- 第二頁的 scrollLeft ≈ 1237.333（遠大於 delta/2 = 618.5）
- 安全邊距巨大，不可能誤判

## 根因

與 004 同系列問題。CSS multi-column 的 sub-pixel rendering 加上 `scrollBy(integer_delta)` 會在每次翻頁累積偏差。`prev()` LTR 的 `left > 0` 判斷對此不夠 robust，累積幾 px 的偏差就會讓已經在第一頁的 scrollLeft 被誤認為「還沒到第一頁」。

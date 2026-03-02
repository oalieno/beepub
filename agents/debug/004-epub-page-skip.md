# Debug: EPUB 翻頁跳頁 (Page Skip on Forward Navigation)

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`

---

## 問題描述

從第 606 頁往前翻，直接跳到 608 頁（跳過 607）。往回翻可以正常翻到 607。不是每一頁都會發生。

## 調查過程

### Phase 1: 加入診斷 log

在 `next()`、`prev()`、`scrolledLocation()`、`paginatedLocation()` 及 `EpubReader.svelte` 的 `relocated` handler 加入 console.log，記錄：
- scroll 位置（scrollLeft/scrollTop）
- layout 參數（delta、width、height）
- 容器尺寸（scrollWidth、offsetWidth）
- 頁碼計算值（startPage、endPage、totalPages）
- 絕對頁碼計算（sectionIdx、sectionPage、prevSectionSum）

### Phase 2: 第一次分析 — sub-pixel scrollLeft

**Log 觀察**（606→608 路徑）：
```
scrollLeft: 21029.333984375
left = scrollLeft + offsetWidth + delta = 21029.33 + 1237 + 1237 = 23503.33
scrollWidth = 23503
23503.33 > 23503 → 判斷為「沒有下一頁」→ 載入下一章節 → 跳到 608
```

**初步修復**：在邊界檢查前對 scrollLeft 做 `Math.round()`。

### Phase 3: 第二次分析 — 累積偏差

修復後仍然有 bug，但路徑不同：605 → 606 → 608。

**Log 觀察**：
```
從 605 (scrollLeft=19792.67) next → 瀏覽器設 scrollLeft=21030（四捨五入向上偏 1px）
從 606 (scrollLeft=21030) next:
  Math.round(21030) + 1237 + 1237 = 23504 > 23503 → 仍然跳章節！
```

問題：瀏覽器 CSS column 的 sub-pixel 對齊會讓 scrollLeft 累積 ±1px 偏差。舊的邊界檢查問的是「下一頁結尾是否在 scrollWidth 內」，這個問法對 ±1px 偏差太敏感。

### Phase 4: 最終修復 — 改變邊界檢查邏輯

**舊邏輯**（太嚴格）：
```javascript
// 問：「下一頁的結尾是否在 scrollWidth 內？」
left = scrollLeft + offsetWidth + delta;
if (left <= scrollWidth)  // 23504 > 23503 → 失敗
```

**新邏輯**（正確）：
```javascript
// 問：「當前可見區域之後是否還有內容？」
left = Math.round(scrollLeft) + offsetWidth;
if (left < scrollWidth)  // 22267 < 23503 → 有內容 → 滾動 ✓
```

**為什麼新邏輯正確**：
- 只要當前可見區域的右邊界（scrollLeft + offsetWidth）還沒到 scrollWidth，就表示後面還有內容
- 瀏覽器會自動把 scrollLeft clamp 到合法範圍，不需要我們預判「下一頁結尾是否剛好在範圍內」
- Math.round 處理 sub-pixel，`<` 而非 `<=` 處理最後一頁的邊界情況

**驗證**：
| 情況 | scrollLeft | 計算 | 結果 |
|------|-----------|------|------|
| 倒數第二頁 (正常) | 21029.33 | round(21029.33)+1237=22266 < 23503 | ✅ 滾動 |
| 倒數第二頁 (偏差+1) | 21030 | 21030+1237=22267 < 23503 | ✅ 滾動 |
| 最後一頁 | 22266 | 22266+1237=23503, NOT < 23503 | ✅ 下一章 |
| 最後一頁 (sub-pixel) | 22266.33 | round(22266.33)+1237=22266+1237=23503, NOT < 23503 | ✅ 下一章 |

同樣的修復也套用到：
- RTL `prev()` 的邊界檢查
- Vertical axis `next()` 的邊界檢查

## 根因

CSS multi-column layout 在瀏覽器中的 scroll 位置並非精確的整數倍。`scrollBy(delta)` 後瀏覽器可能將 scrollLeft snap 到附近的 sub-pixel 位置，累積後產生 ±1px 偏差。原始 epub.js 的邊界檢查對此不夠 robust。

## 關鍵學到的教訓

1. **瀏覽器 scrollLeft 是 float**：CSS column 的 sub-pixel rendering 導致 scrollLeft 不是精確的整數倍
2. **邊界檢查應問「是否還有內容」而非「下一頁是否完全在範圍內」**：後者對 ±1px 偏差太敏感
3. **偏差會累積**：連續翻頁（scrollBy）後偏差可能從 0.33 變成 1.0，需要考慮最壞情況

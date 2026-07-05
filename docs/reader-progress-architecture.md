# 閱讀器進度系統架構

**日期**：2026-07
**範圍**：`frontend/src/lib/components/reader/EpubReader.svelte`、`frontend/src/lib/epubjs/locations.js`、`frontend/src/lib/services/locationsCache.ts`

這份文件解釋閱讀進度的兩套計算系統為什麼同時存在、每個欄位的流向、以及修改這區時必須維持的不變量。背景：這區是三代機制疊加的結果，知識散在 debug docs 裡，容易誤判成 dead code（頁數顯示已移除，但頁數機制仍是進度恢復的底層）。

## 歷史演進

| 代 | 機制 | 結局 |
|---|------|------|
| 1 | Hidden book instance 逐章渲染算精準頁數 | 開書轉圈圈很久、游標閃爍、互動被擋、sub-pixel bug 一堆（debug 001/004/005/006）。整套移除，見 debug 008、commit `191a667` |
| 2 | 懶惰頁數估算：只記「實際翻過的章節」render 時得到的頁數（`sectionPageCounts`），沒翻過的用平均值估 | 保留至今，作為 fallback 與恢復校正 |
| 3 | epub.js locations 作為文字書的 canonical 進度（commit `c493cf4`，2026-04） | 現行主系統；2026-07 加上 IndexedDB 快取 |

## 兩套系統

### 系統 A：Locations（canonical，文字書）

- `epubBook.locations.generate(1600)` 抓每個章節的**原始 HTML**（不渲染），用 TreeWalker 數字元，每 1600 字元記一個 CFI。
- **與排版完全無關**：字級、行距、邊距、視窗大小都不影響結果。輸入只有書檔內容 → 結果對同一書檔固定 → 可以快取。
- 快取：`locationsCache.ts`（IndexedDB，key = bookId，fingerprint = uniqueIdentifier + spine 數 + 切分粒度，LRU 上限 40 本）。書檔重傳會改變 fingerprint 而失效。
- 消費者：
  - `location.start.percentage` → 顯示的百分比（canonical）
  - `cfiFromPercentage()` → 進度條滑桿跳轉（`displayPercentage()`）
- 大書首開仍需完整生成一次（幾秒～幾十秒），期間進度顯示為空（見不變量 1）。

### 系統 B：頁數估算（fallback ＋恢復校正）

- `sectionPageCounts[i]`：第 i 章渲染後實際排出的頁數，**翻到才記錄**（`updateSectionPageCount`），沒翻過的章節以已知章節的平均值代打。
- **與排版有關**：字級/視窗改變 → 各章頁數變 → 這是「頁數會重算」印象的來源。重算是每章 render 時順便發生的，成本低，與慢的 locations generate 無關。
- 用途（皆為必要，非 dead code）：
  1. **進度恢復校正**：CFI 恢復有字元偏移精度誤差（off-by-one page）。恢復流程 = `display(cfi)` → `scrollToPageIndex(section_page)` 校正（`_lastTargetPage` 邏輯，見 debug 001；vertical-rl 特別依賴）。校正**只在 `font_size` 與存檔時相同**才做。
  2. **locations 未就緒前的百分比估算**：`calculatePageProgress()` 用章節頁數加權估進度（但估算值不落庫也不顯示，見不變量 1）。
  3. **圖片書／漫畫的唯一進度來源**：圖片書沒有文字可數，`locations.generate` 常失敗（`generateLocations` 的 catch 分支），全程走頁數估算。
  4. **`atEnd` 判定載體**：翻到最後一章最後一頁 → `location.atEnd` → percentage = 100 → 自動標記讀完。

## 進度欄位流向

`saveProgress()` 每 30 秒（backup）＋ relocated debounce 存到後端，同時鏡射到 localStorage（`reader-progress-{bookId}`，離線/iOS PWA resume fallback）：

| 欄位 | 產生者 | 消費者 | 可否移除 |
|------|--------|--------|---------|
| `cfi` | relocated | 恢復定位主鍵 | ❌ |
| `percentage` | 系統 A（文字書）／系統 B（圖片書） | 詳情頁、書卡進度、自動標記讀完 | ❌ |
| `section_index` | relocated | 恢復、prefetch | ❌ |
| `section_page` | relocated（`displayed.page`） | **恢復校正**（scrollToPageIndex） | ❌ |
| `section_page_counts` | 系統 B 懶惰收集 | 重開書時 seed 系統 B，圖片書進度連續性 | ❌ |
| `font_size` | 設定 | 判斷 `section_page` 校正是否適用 | ❌ |
| `current_page` / `total_pages` | 系統 B | 目前無 UI 顯示（頁數顯示已移除） | ⚠️ 理論上可移除，但不值得為此動這區 |

## 關鍵旗標

| 旗標 | 意義 |
|------|------|
| `locationsGenerated` | 系統 A 就緒（generate 完成或快取載入）。就緒後觸發 `onlocationsready` → 進度條滑桿啟用 |
| `waitingForCanonicalProgress` | 文字書且系統 A 未就緒：期間 `emitProgress(null)`（UI 不顯示估算值）、`saveProgress` 直接 return（估算值不落庫） |
| `restoringProgress` | 恢復定位進行中：relocated 事件不觸發儲存／進度計算，避免把恢復過程的中間位置存掉 |
| `reachedEnd` | 本次 session 曾觸發 `atEnd`（進入自動標記讀完的條件之一） |
| `autoReadTriggered` / `autoReadSuppressed` | 自動標記讀完只觸發一次；使用者按「復原」後本 session 不再自動標記 |

## 不變量（修改時必須維持）

1. **fallback 估算值不落庫、不顯示**：`waitingForCanonicalProgress && !locationsGenerated` 期間，`saveProgress` 不送、`emitProgress(null)`。違反的後果：不準的百分比寫進資料庫，之後 locations 就緒時進度跳動（`c493cf4` 就是在修這個）。
2. **恢復期間不儲存**：`restoringProgress` 為 true 時 relocated 不觸發 save。違反的後果：恢復過程的中間頁覆蓋掉真正的進度。
3. **`section_page` 校正僅限同字級**：`savedProgress.font_size === fontSize` 才做 scrollToPageIndex 校正；字級變了頁數映射就無效，只能信 CFI。
4. **自動標記讀完的觸發條件**：`(percentage >= 99 || reachedEnd) && !autoReadTriggered && !autoReadSuppressed`。99% 涵蓋結尾是版權頁的書（讀者不會真的翻到底），`reachedEnd` 涵蓋估算卡在 98% 的書；誤觸由 undo toast 兜底。
5. **圖片書不等 locations**：`waitingForCanonicalProgress = !isImageBook`——圖片書直接用系統 B，不會被卡在「等待 canonical」狀態。

## 修改警告

- **不要**重新引入任何「開書時預先計算全書精準頁數」的機制——那是第一代的老路，debug 008 記錄了為什麼放棄。
- **不要**動 `section_page` / `section_page_counts` 的儲存與恢復——vertical-rl 的頁面恢復依賴它（debug 001/006/009/016）。
- epub.js fork 的修改守則見 `.agents`／memory：不要動 `expand`，翻頁問題在 `next()`/`prev()` 修。
- locations 快取的 fingerprint 如果要改（例如換切分粒度 1600），舊快取會自動失效重算，不需要遷移邏輯。

## 相關 debug docs

- 001 — CFI 恢復 off-by-one 與 `section_page` 校正的由來
- 004/005/006 — 第一代精準頁數的 sub-pixel 問題
- 008 — 移除 hidden book，改用百分比（第一代 → 第二代）
- 009/016 — vertical-rl 分頁與恢復
- 019 — mixed-layout / pre-paginated 章節

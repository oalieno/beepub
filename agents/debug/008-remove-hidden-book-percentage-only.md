# 008 — 移除 Hidden Book，改用百分比顯示進度

## 狀態：✅ 已完成

## 問題

EPUB 閱讀器為了精確計算全書頁數，會在背景建立一個 hidden book instance（隱藏的 iframe），逐一遍歷所有 spine items 並渲染以取得每個 section 的頁數。這導致：

1. **游標 flickering** — 隱藏 iframe 快速翻頁時干擾主畫面
2. **互動被阻擋** — 計算期間整個閱讀區域 `pointer-events-none` + `opacity-50`
3. **啟動慢** — 每次開書或改字型都要重跑一次完整的 page map 計算
4. **大量 sub-pixel 相關 bug** — debug 001, 004, 005, 006 都與精確頁數計算有關

## 解法

使用者決定改為只顯示 **百分比**，利用主 rendition 的 `relocated` 事件中已有的資料計算：

```
percentage = (sectionIndex + currentSectionPage / displayedTotal) / totalSections * 100
```

- `sectionIndex`、`currentSectionPage`、`displayedTotal` 來自 `location.start`
- `totalSections` = `book.spine.spineItems.length`
- 各 section 權重相等（近似值，但使用者接受）
- 中英文字數差異、字型大小、視窗比例都已反映在 `displayedPage` / `displayedTotal`

## 修改的檔案

### `frontend/src/lib/components/reader/EpubReader.svelte`
- **移除** `calculatePageMap()` — 整個 hidden book 邏輯
- **移除** `initOrRecalcPageMap()` — page map 初始化
- **移除** page map cache (`pageCacheKey`, `loadCachedPageMap`, `saveCachedPageMap`)
- **移除** `computeAbsolutePage()`, `computeTotalPages()`
- **移除** `handleResize()` — 不再需要，resize 後 `relocated` 自動觸發
- **移除** 狀態變數：`sectionPageCounts`, `pageMapReady`, `currentPage`, `totalPages`, `calculatingPages`, `pendingResize`, `resizeDebounceTimer`
- **移除** template 上的 `class:pointer-events-none` 和 `class:opacity-50`
- **簡化** `relocated` handler — 直接算百分比
- **簡化** `saveProgress()` / `handleBeforeUnload()` — 不再送 `current_page`, `section_page_counts`, `total_pages`
- **簡化** `onprogress` callback type — 只有 `{ cfi, percentage }`
- **保留** CFI + `section_page` 還原機制（`scrollToPageIndex` 修正）

### `frontend/src/lib/components/reader/Toolbar.svelte`
- 移除 `currentPage`, `totalPages`, `pageMapReady`, `calculatingPages` props
- 進度顯示從 `X% · 123 / 456 🔄` 改為 `X%`

### `frontend/src/routes/books/[id]/read/+page.svelte`
- 移除 `currentPage`, `totalPages`, `pageMapReady`, `calculatingPages` state
- 底部指示器從頁碼改為 `X%`

### `frontend/src/lib/api/books.ts`
- `updateProgress` type 移除 `current_page`, `section_page_counts`, `total_pages`

### Backend — 無需修改
- `ProgressUpdate` schema 中這些欄位本來就是 `Optional`，前端不送即可
- DB 中舊的 JSONB 資料不受影響

## 保留的功能

- **位置還原**：CFI + `scrollToPageIndex(section_page)` 修正，進出閱讀器不會跑位
- **epubjs fork 修正**：`_lastTargetPage`, `afterResized`, sub-pixel tolerance 全部保留
- **進度儲存**：debounce 2s + 定時 30s + beforeunload keepalive

## 百分比公式邊界值

| 位置 | 計算 | 結果 |
|------|------|------|
| 第一頁 | `(0 + 1/T) / N * 100` | 小正數（已開始閱讀）|
| 最後一頁 | `(N-1 + T/T) / N * 100` | `100%` |
| 單 section 書 | `(0 + p/T) / 1 * 100` | `p/T * 100` |

## 刪除約 150 行，無新增依賴

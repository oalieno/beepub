# Debug: Mobile Reader UX + Safari 文字異常 + SSR 500

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `frontend/src/routes/books/[id]/read/+page.svelte`
- `frontend/src/lib/components/reader/EpubReader.svelte`
- `frontend/src/lib/components/reader/Toolbar.svelte`
- `frontend/src/routes/books/[id]/+page.svelte`

---

## 問題 1：手機閱讀頁左右留白不足、上下滑動造成 UX 不穩

### 現象
- 手機閱讀頁內容太貼邊。
- 出現 vertical scrollbar，滑動時會有上下亂動。

### 根因
- Reader 容器未明確限制 overflow 與 touch 方向。
- 頁面層有機會被 mobile browser 視窗行為觸發垂直滾動。

### 修復
1. Reader 外層加入 `overflow-hidden`、`touch-pan-x`、mobile `px-3`。
2. 左右翻頁 tap zone 手機寬度從 `w-14` 提升到 `w-20`。
3. 進入 `/books/[id]/read` 時鎖定 `html/body overflow=hidden`，離開頁面還原原設定。

---

## 問題 2：Safari 手機部分行文字異常放大

### 現象
- 僅 Safari 出現少數段落字體比其他行大。

### 根因
- Safari 觸發 text inflation（自動文字縮放調整）。

### 修復
- 在 `rendition` 與 `hiddenRendition` 主題都加入：
  - `-webkit-text-size-adjust: 100%`
  - `text-size-adjust: 100%`

---

## 問題 3：同時開 Safari/Chrome 讀同一本時，`/read` 偶發 500

### 現象
- Server log: `ReferenceError: document is not defined`。

### 根因
- `+page.svelte` 的 `onDestroy` 在 SSR 階段執行時直接存取 `document`。

### 修復
- 加入 `browser` guard：`if (!browser) return;` 後才觸碰 `document`。

---

## 問題 4：書籍詳情頁 action icons 與標題擠在一起（手機）

### 現象
- 標題和 admin actions 同一行，長標題下可讀性差。

### 修復
- 將 details 標題區改為 mobile `flex-col`，actions 自動落到標題區塊下方；桌面維持左右布局。

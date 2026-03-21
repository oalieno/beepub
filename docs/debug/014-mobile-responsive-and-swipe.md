# Mobile Responsive Design 修復 + Swipe 翻頁

**日期**：2026-03
**狀態**：✅ 已修復

---

## 修復項目

### 1. Navbar 透明背景疊加
- **問題**：`<nav>` 是 `fixed` 但沒有背景色，滾動時與內容重疊
- **修復**：加 `bg-background/80 backdrop-blur-md border-b border-border/50`
- **檔案**：`Navbar.svelte`

### 2. "Start Reading" 按鈕換行
- **問題**：手機螢幕太小時文字折成兩行
- **修復**：加 `whitespace-nowrap text-sm sm:text-base px-4 sm:px-6`
- **檔案**：`books/[id]/+page.svelte`

### 3. Book detail 手機板 Description 排序
- **問題**：手機板長 Description 在短 metadata（Publisher/ISBN）之前
- **修復**：Description 加 `order-last md:order-none`，metadata 加 `order-first md:order-none`
- **檔案**：`books/[id]/+page.svelte`

### 4. Admin Users 表格溢出
- **問題**：5 欄表格在手機上超出版面
- **修復**：容器加 `overflow-x-auto`，table 加 `min-w-[600px]`
- **檔案**：`admin/users/+page.svelte`

### 5. Swipe 翻頁

#### 發現：Snap 模組從未啟用

epub.js 的 `Snap` 模組只在 `continuous` manager 中使用（`managers/continuous/index.js`）。
我們用的是 `default` manager，所以 snap 從來沒有被啟用過。
之前 log 010 寫的 "swipe/tap page navigation is handled by epub.js snap module" 是錯誤假設。

#### 實作

在 `EpubReader.svelte` 的 iframe content hook 中加入 swipe 偵測：

**iOS 路徑**（已有 touch state machine）：
- 在 `touchend` handler 中，當 `touchState === "swiping"` 時
- 檢查 `|dx| > 50px`（SWIPE_THRESHOLD）
- 根據滑動方向和 RTL 設定呼叫 `rendition.prev()/next()`
- 與長按選取不衝突：移動 >10px 就進入 swiping 狀態，不會觸發選取

**非 iOS 路徑**（新增）：
- 在 iframe document 上註冊 touchstart/touchmove/touchend
- touchstart：記錄起始座標
- touchmove：移動 >10px 標記為 swiping
- touchend：
  - 如果 swiping 且 `|dx| > 50px`：檢查無文字選取後翻頁
  - 如果非 swiping（tap）：延遲 300ms 嘗試顯示 highlight menu
- 所有 listener 都是 `passive: true`

#### 與 highlight 選取的共存
- iOS：state machine 保護（swiping 和 selecting 是互斥狀態）
- 非 iOS：翻頁前檢查 `selection.isCollapsed`，有選取就不翻頁

### 6. Reader 左右留白與 tap zone 對齊（gap 機制修正）

#### 問題
- 嘗試在 `EpubReader.svelte` theme 裡改 `body.padding`（例如 `2rem 3rem`）後，手機實機看起來留白沒有變大。

#### 根本原因
- epub.js 在 `contents.js -> columns()` 會再次設定 body padding：
  - 水平排版：`padding-left/right = gap / 2`（含 `!important`）
  - 垂直排版：`padding-top/bottom = gap / 2`
- 因為是 runtime 寫入且使用 `!important`，theme 的 `body.padding` 會被覆蓋。
- 在 paginated 模式下，**視覺留白與分頁幾何（column width / page delta）是同一套 gap 計算**，不能只改 CSS padding。

#### 正確修復方式
- 改 `layout.js` 的 gap 計算，而不是只改 theme padding。
- 在 `reflowable + paginated + auto gap` 路徑加下限：`gap = Math.max(gap, 96)`。
- 這樣在手機上會得到每側 `48px` 留白（`gap/2`），並與 reader tap zone `w-12` 對齊。

#### 結果
- 手機：左右留白實際變大，tap zone 擴大後仍主要落在留白區域，不遮文字。
- 桌面：原本自動 gap 足夠時不受影響。

---

## 修改的檔案
- `frontend/src/lib/components/Navbar.svelte`
- `frontend/src/routes/books/[id]/+page.svelte`
- `frontend/src/routes/admin/users/+page.svelte`
- `frontend/src/lib/components/reader/EpubReader.svelte`
- `frontend/src/lib/epubjs/layout.js`

# iOS Custom Text Selection Implementation

## Problem

在 iPhone PWA（加到主畫面）中，選取 epub 文字只會觸發原生 iOS 選取 UI（藍色選取 + 放大鏡 magnifier + 拷貝/查詢/翻譯 callout），無法觸發我們自訂的 highlight menu（顏色、複製、AI illustration）。

## 核心挑戰

iOS Safari/WebKit 的文字選取行為深度整合在系統層級，且 epub.js 使用 sandboxed iframe 渲染內容，兩者交互產生多個難題。

## 嘗試過的方法（按時間順序）

### 1. CSS `-webkit-touch-callout: none` (失敗)
- 只影響連結/圖片的長按 callout，不影響文字選取 menu
- 對 text selection 完全無效

### 2. `selectionchange` + `touchend` 事件 (失敗)
- iframe sandbox 設定為 `allow-same-origin`（無 `allow-scripts`）
- **所有 JS 事件處理器在 iframe 內被封鎖**
- 錯誤訊息：`Blocked script execution in 'about:srcdoc'`

### 3. `allowScriptedContent: true` (突破點)
- epub.js rendition 選項，將 iframe sandbox 改為 `allow-same-origin allow-scripts`
- 事件處理器終於可以在 iframe 內執行
- **安全隱患**：epub 內嵌的惡意 script 也能執行
- **解決**：注入 `<meta http-equiv="Content-Security-Policy" content="script-src 'none'">` 到 iframe head，封鎖 epub script 但允許事件處理

### 4. Calibre 研究（關鍵參考）
- 研究了 `kovidgoyal/calibre` 的原始碼：
  - `src/pyj/read_book/selection_bar.pyj` - 自訂選取列
  - `src/pyj/read_book/touch.pyj` - 觸控事件處理（750ms 長按偵測）
  - `src/pyj/read_book/iframe.pyj` - 選取變化監控
- **Calibre 的做法**：`preventDefault()` 所有觸控事件 + `user-select: none` + `caretRangeFromPoint` 程式化選取

### 5. 自訂長按選取（最終方案基礎）
- `user-select: none` 在 iframe body
- 500ms 長按計時器
- `document.caretRangeFromPoint(x, y)` 取得觸控位置的文字節點
- 程式化建立 Selection + Range

## 最終實作方案

### CSS 注入（iframe 內）
```css
* { -webkit-touch-callout: none !important; }
body { -webkit-user-select: none !important; user-select: none !important; touch-action: pan-x pan-y; }
body.beepub-selecting { -webkit-user-select: text !important; user-select: text !important; }
```

### Touch State Machine
```
IDLE → touchstart → WAITING (500ms timer)
  ├─ 移動 >10px → SWIPING (epub.js snap 處理翻頁)
  ├─ 500ms 到期 → SELECTING (選取文字)
  │   └─ 移動 >15px → 拖曳延伸選取
  └─ 快速放開 → tap（翻頁或關閉 menu）
```

### 關鍵技術細節

#### `beepub-selecting` class 的生命週期（最難搞的部分）
1. `selectWordAt()` 開始：加上 `beepub-selecting`（啟用 `user-select: text`）
2. 呼叫 `caretRangeFromPoint()`（需要 `user-select: text` 才能找到文字位置）
3. `getSelection().addRange(range)` 建立選取
4. **立刻** `cloneRange()` 保存 range 和 `sel.toString()` 保存文字
5. **立刻** 移除 `beepub-selecting`（回到 `user-select: none`）
6. 繪製自訂 overlay

**為什麼要立刻移除？**
- 如果保留 `beepub-selecting`，`user-select: text` 持續啟用
- 後續觸控會觸發原生 iOS magnifier + 選取 UI
- 必須在取得 range/text 後立刻關閉

**為什麼要先保存 range/text？**
- 移除 `beepub-selecting` 後 `user-select: none` 生效
- `getSelection()` 會變成 collapsed/empty
- 無法再從 selection 取得文字或 range
- 所以必須在移除前用 `cloneRange()` 和 `toString()` 保存

#### CJK vs Latin 選取
- CJK（中日韓）：選取單一字元（無空格分詞）
- Latin：擴展到詞邊界（空格/標點分隔）

#### 自訂選取 Overlay
- 原生 `::selection` 在 `user-select: none` 下不渲染
- 用 `Range.getClientRects()` 取得所有文字矩形
- 在 iframe body 內建立 `position:absolute` 的藍色半透明 div 覆蓋

#### Highlight Menu 定位
- 用 `range.getBoundingClientRect()` 取得選取範圍位置
- 減去 `container.scrollLeft/scrollTop` 轉換到可視區域座標
- `setClampedMenuPosition()` 確保 menu 不超出容器邊界
- 用 `bind:this={highlightMenuEl}` 取得實際 menu 寬度做精確 clamp

#### 防止 Menu Jitter
- 長按放開時手指微小移動（tremor）會觸發 `didDragSelect`
- 設定 >15px 門檻才算拖曳延伸
- 只有實際拖曳才在 touchend 重新計算 menu 位置

### 與 epub.js snap 模組的共存
- epub.js 的 snap 模組（`managers/helpers/snap.js`）自己處理觸控翻頁
- snap 監聽 scroller 的 touchstart/touchmove/touchend + iframe 的 contents 事件
- **不能** 在我們的 touch handler 呼叫 `rendition.next()/prev()`，否則會 double navigation（oscillation：page 4→3→4→3）
- 翻頁完全交給 snap；我們只處理長按選取和 menu 互動

### 父容器 CSS
```html
<div style="-webkit-touch-callout: none; -webkit-user-select: none; user-select: none;">
```
防止在 iframe 外的區域（邊緣按鈕等）觸發原生全選。

## 修改的檔案
- `frontend/src/lib/components/reader/EpubReader.svelte` - 主要邏輯（iOS touch state machine、overlay、menu）
- `frontend/src/lib/components/reader/HighlightMenu.svelte` - 新增 Copy 按鈕

## 踩過的坑（教訓）

1. **iframe sandbox 是最大的坑**：沒有 `allow-scripts` 就沒有任何事件處理器能執行，所有 addEventListener 都是死的
2. **`user-select: none` 是雙面刃**：能擋住原生 UI，但也讓 `caretRangeFromPoint` 和 `getSelection` 失效，必須精確控制啟用/停用時機
3. **不要同時處理翻頁**：epub.js snap 已經在處理了，重複處理 = 翻頁混亂
4. **`preventDefault` on touchstart 會搞壞一切**：連結點不了、click 事件不觸發、epub.js 內部機制壞掉
5. **iOS magnifier 只要 `user-select: text` 就會出現**：即使只是暫時啟用，如果沒有在同一個 tick 內關閉，iOS 就會偵測到並顯示 magnifier
6. **`::selection` CSS 在程式化選取 + `user-select` toggle 下不可靠**：必須自己畫 overlay

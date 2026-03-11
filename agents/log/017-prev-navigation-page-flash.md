# Debug: prev() 往回翻頁時閃一下錯誤頁面

**日期**：2026-03
**狀態**：✅ 已修復
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`

---

## 問題摘要

從章節開頭往回翻（prev）到上一章時，會閃現上一章中段的某一頁（約零點幾秒），然後才跳到正確的最後一頁。水平和垂直模式都會發生。結果正確，但中間有視覺閃爍。

---

## 根因分析

### expand() 多階段 resize 導致 scrollWidth/scrollHeight 劇烈變化

prev() 的流程：
1. `clear()` → 移除當前 view
2. `prepend()` → 建立新 view（`visibility: hidden`），載入內容，觸發第一次 expand
3. `.then()` → 根據當前 scrollWidth/scrollHeight 滾到尾端，然後 `views.show()`
4. ResizeObserver 觸發更多 expand 循環 → scrollHeight 大幅增長 → `counter()` 調整位置

### 實際 log 數據（垂直模式）

```
第一次 resize: heightDelta=21725, scrollHeight=21725
  → counter 滾到 20856（第 24/25 頁）
  → .then() 執行 scrollToEnd + show()  ← 此時 view 變可見，用戶看到第 24 頁

第二次 resize: heightDelta=53878, scrollHeight=75603（暴增 3.5 倍）
  → counter 滾到 74734（第 86/87 頁）  ← 正確位置，但用戶已經看到閃爍
```

content 從 21725 膨脹到 75603，第一次 expand 只測量到部分內容，view 就已被 show。

### 為什麼 requestAnimationFrame 沒用

嘗試用 rAF 延遲 show，但第二次 resize 發生在 rAF 之後的下一幀（每次 reframe 觸發新的 ResizeObserver，在下一幀才回調），所以 rAF 只多等了一幀，仍然在第二次 resize 之前就 show 了。

---

## 修復方案

### ✅ 最終方案：debounce show

核心思路：view 保持 `visibility: hidden`，直到 resize 穩定後才 show。

新增兩個方法：
- `_scrollToEnd()` — 根據軸和方向滾到章節尾端（提取自原本 .then 中的邏輯）
- `_scrollToEndAndShow()` — 立即 scrollToEnd，然後設 100ms debounce timer

修改 `counter()`：如果 `_pendingShowTimer` 存在，每次 resize 時重新 scrollToEnd + 重設 timer。

流程：
1. prev() → prepend → `.then()` 呼叫 `_scrollToEndAndShow()`
2. 立即 scrollToEnd（view 仍 hidden），設 100ms debounce timer
3. 每次 counter() 被 resize 觸發 → 偵測到 pending timer → 重新 scrollToEnd + 重設 timer
4. resize 停止超過 100ms → timer 觸發 → 最後一次 scrollToEnd + `views.show()`

```javascript
_scrollToEndAndShow() {
  this._scrollToEnd();
  this._pendingShowTimer = setTimeout(() => {
    this._scrollToEnd();
    this.views.show();
    this._pendingShowTimer = null;
  }, 100);
}
```

counter() 開頭加入：
```javascript
if (this._pendingShowTimer != null) {
  this._scrollToEnd();
  clearTimeout(this._pendingShowTimer);
  this._pendingShowTimer = setTimeout(() => {
    this._scrollToEnd();
    this.views.show();
    this._pendingShowTimer = null;
  }, 100);
}
```

`clear()` 中清理 timer 防止記憶體洩漏。

### 關鍵考量

- 100ms debounce 延遲幾乎不可感知
- view 在 expansion 完全穩定前始終 `visibility: hidden`，不會有任何閃爍
- 適用於水平和垂直兩種模式

---

## 嘗試過但失敗的方案

### ❌ requestAnimationFrame 延遲 show

在 .then() 中用 rAF 包裹 scrollToEnd + show。理論上 ResizeObserver 在 rAF 之前觸發，但實際上 expand 的多輪 resize 跨越多個 frame，rAF 只多等一幀不夠。

---

## 相關檔案

- `frontend/src/lib/epubjs/managers/default/index.js` — prev()/counter()/_scrollToEndAndShow()
- `frontend/src/lib/epubjs/managers/views/iframe.js` — expand()/reframe() 觸發 resize
- `agents/log/016-rtl-titlepage-blank-pages.md` — 相關的 expand 無限迴圈問題

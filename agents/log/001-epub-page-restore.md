# Debug: EPUB Off-by-One Page Restore

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `frontend/src/lib/epubjs/managers/default/index.js`
- `frontend/src/lib/epubjs/contents.js`
- `frontend/src/lib/components/reader/EpubReader.svelte`
- `frontend/package.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`

---

## 問題描述

儲存在第 500 頁，重新開啟後落在第 499 頁（off-by-one）。

## 調查過程

### Phase 1: Fork epub.js

epub.js (npm v0.3.93) 無法直接修改，所以將原始碼複製到 `frontend/src/lib/epubjs/`，設為本地 fork。

- **Vite alias 無效**：`vite.config.ts` 的 `resolve.alias` 對動態 `import('epubjs')` 不起作用。
- **解法**：直接改 `EpubReader.svelte` 的 import 為 `import('$lib/epubjs/epub.js')`。
- 也需要把 epub.js 的 runtime deps 加到 `package.json`（pnpm strict resolution）。
- `tsconfig.json` exclude `src/lib/epubjs/**` 避免大量 TS 報錯。

### Phase 2: Scroll capping bug

**問題**：`moveTo()` 的 scroll 目標被 `container.scrollWidth` cap 住。字體載入前 `scrollWidth` 很小，所以初始 scroll 被截斷到錯誤位置。之後字體載入、content 擴展，但 `afterResized()` 發出的是 `EVENTS.MANAGERS.RESIZE`，而 rendition 只監聽 `EVENTS.MANAGERS.RESIZED`（多了 D），所以 scroll 永遠不會被重新調整。

**修復**：
1. `display().then()` 中儲存 `_lastTarget`
2. `afterResized()` 中若 `_lastTarget` 存在則重新 `moveTo()`
3. `next()`/`prev()` 清除 `_lastTarget` 避免翻頁後回彈

### Phase 3: Sub-pixel rounding

**問題**：`moveTo()` 使用 `Math.floor(offset.left / delta)` 計算頁碼，`getBoundingClientRect()` 回傳的 sub-pixel 值（如 20823.999）被 floor 到前一頁。

**修復**：加 3px tolerance：`Math.floor((offset.left + 3) / delta)`

### Phase 4: CFI 精度不足（Root Cause）

**問題**：以上修復後仍然 off-by-one。深入分析 console log 發現：

```
saved CFI: epubcfi(/6/54!/4/2/532/1:0)  saved page: 500
locationOf result: {left: 20823}         ← 元素起始位置
position rect width: 1746                ← 元素跨 2 頁！
```

CFI `532/1:0` 的 `:0` 表示 character offset 0（元素開頭）。但該元素跨越多頁，使用者實際在第二頁。`locationOf` 永遠回傳元素的左邊界（第一頁），導致 off-by-one。

**根因**：CFI → `locationOf` → pixel offset 這條路徑本質上有精度損失。

**修復**：bypass CFI 路徑，改用儲存的 `section_page` 直接計算 scroll offset：

```javascript
// EpubReader.svelte — 在 display() resolve 後
const mgr = rendition.manager;
const targetPage = savedProgress.section_page - 1; // 0-indexed
mgr._lastTarget = null;
mgr._lastTargetPage = targetPage;
const distX = targetPage * mgr.layout.delta;
if (distX + mgr.layout.delta <= mgr.container.scrollWidth) {
  mgr.scrollTo(distX, 0, true);
  mgr._lastTargetPage = null;
}
```

`afterResized()` 中也支援 `_lastTargetPage`，在 `scrollWidth` 不夠大時延遲重試。

### Phase 5: rendition.manager 不存在

**問題**：最初嘗試在 `display()` 之前設定 `rendition.manager._lastTargetPage`，但 `rendition.manager` 在第一次 `display()` 呼叫前不存在。TypeError 被 try/catch 捕獲，落入 `catch { await rendition.display() }`（無 CFI）→ 永遠回到第 1 頁。

**修復**：改為在 `await rendition.display(savedProgress.cfi)` 之後才設定 `_lastTargetPage` 並修正 scroll 位置。

## 關鍵學到的教訓

1. **epub.js CFI 精度有限**：跨多頁的元素，CFI character offset 0 永遠指向元素開頭
2. **scrollWidth 在字體載入前不可靠**：需要 afterResized 重試機制
3. **Vite alias 對動態 import 無效**：改用直接路徑
4. **rendition.manager 延遲建立**：第一次 display() 前不存在

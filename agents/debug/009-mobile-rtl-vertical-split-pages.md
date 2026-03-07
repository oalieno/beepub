# Debug: Mobile RTL 直排書顯示裂頁（同時出現兩頁各一半）

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `frontend/src/lib/components/reader/EpubReader.svelte`
- `frontend/src/lib/epubjs/managers/default/index.js`

---

## 問題摘要

在手機板（螢幕較小）閱讀某些 **RTL 直排 EPUB** 時，畫面會出現裂頁：

- 同時看到前後兩頁各一半
- 看起來像 scroll 停在頁與頁的中間
- 問題主要出現在重新進入書籍、依進度恢復位置時

---

## 代表性 log（節錄）

```text
[moveTo] offset.top: 14824 pageStep: 871.3333740234375 page (0-idx): 17 distY: 14812.667358398438 scrollHeight: 21775
[scrollTo] x:0 y:14812.667358398438 silent:true scrollLeft:0->0
[scrollTo] x:0 y:15684.000732421875 silent:true scrollLeft:0->0
[scrolledLocation] index: 13 startPos: 15684.00065612793 endPos: 16535.334030151367 stopPos: 851.3333740234375 currPage: 19 endPage: 20 totalPages: 84 vertical: true rtl: true
```

關鍵現象：
- 先發生一次 `moveTo()`
- 接著又出現第二次 `scrollTo()` 把位置往後推
- 最終頁面停在裂頁位置

---

## 一開始的懷疑方向

### 1) vertical paginated 的 page step 計算不一致
曾懷疑是：
- `moveTo()` / `next()` / `prev()` 用的 page step
- 與 `scrolledLocation()` 計算目前頁用的可視高度

兩者不一致，造成 scroll snap 停在頁縫中間。

因此曾在 `frontend/src/lib/epubjs/managers/default/index.js` 補強：
- `vertical` 路徑的 `getPageStep()`
- `scrollToPageIndex()` / `moveTo()` / `next()` / `prev()` 都改用同一套 vertical page-step 邏輯
- `updateAxis()` 在 spread 狀態變化時立即 `updateLayout()`

這些修正讓 vertical 路徑更一致，但**沒有真正解掉這次裂頁問題**。

---

## 真正根因

### `display(cfi)` 後又被 `section_page` 做第二次 restore
`EpubReader.svelte` 的進度恢復流程原本是：

1. `await rendition.display(savedProgress.cfi)`
2. 若有 `savedProgress.section_page`，再呼叫 manager 的 page-based restore

這個做法對一般 horizontal 書可用，但對這本 **RTL + vertical + paginated** 書會造成：

- `display(cfi)` 已先透過 epub.js 做一次正確定位
- 緊接著又依 `section_page` 再做一次 page-based 校正
- 第二次校正把畫面推到頁與頁中間
- 最終出現「兩頁各露一半」的裂頁畫面

也就是說，**問題不是只有 page step，而是 vertical 書被重複定位兩次**。

---

## 最終修復

### 在 vertical 書跳過 `section_page` 二次 restore
修改：`frontend/src/lib/components/reader/EpubReader.svelte`

在：

```ts
await rendition.display(savedProgress.cfi);
```

之後，加入判斷：

- 若 `mgr.settings.axis === 'vertical'`
- 則**不再**套用 `savedProgress.section_page` 的 page-based restore
- 只保留 `display(cfi)` 的定位結果

### 保留的 fork 強化
`frontend/src/lib/epubjs/managers/default/index.js` 仍保留先前補過的 vertical 路徑改善：

- `updateAxis()` 在 spread 狀態改變時重算 layout
- `scrollToPageIndex()` / `moveTo()` / `next()` / `prev()` 走 vertical-aware page step

雖然這些不是這次最終命中的核心修復，但可避免 vertical 分頁路徑日後再出現不一致。

---

## 驗證結果

修正後：

- 手機板重新開啟這本 RTL 直排書
- 畫面恢復正常
- 不再出現同時露出兩頁各一半的裂頁現象

---

## 備註

這次問題的關鍵教訓是：

- `CFI restore` 與 `section_page restore` 不能在所有 writing mode / axis 上一概而論
- 對 `vertical paginated` 書，`display(cfi)` 後再做 page-based restore 可能反而破壞定位
- 後續若再做進度恢復優化，應將 restore 策略區分為：
  - horizontal paginated
  - vertical paginated
  - scrolled

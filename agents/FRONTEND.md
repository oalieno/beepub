# BeePub 前端

## 路由

```
/              首頁（最近新增、書架、統計）
/login
/libraries     所有可見圖書館
/libraries/[id] 圖書館書籍（搜尋、排序、篩選）
/books/[id]    書籍詳情（metadata、評分、書評）
/books/[id]/read  EPUB 閱讀器
/bookshelves   我的書架列表
/bookshelves/[id] 書架書籍
/admin         管理儀表板
/admin/libraries  管理圖書館（visibility、白名單）
/admin/libraries/[id] 管理特定圖書館
/admin/users   管理使用者（角色、停用）
```

## EPUB 閱讀器功能

- 使用 **epubjs 本地 fork**（`frontend/src/lib/epubjs/`）在瀏覽器端渲染
- epub 從 `GET /api/books/{id}/file` 串流載入
- 進度：CFI 位置自動儲存（每30秒 + 翻頁時），含 section_page 用於精確恢復
- 螢光筆：5色（黃/綠/藍/粉/橙），點選文字彈出選單
- 每個 highlight 可附加文字註解
- 字體切換：serif / sans-serif（透過 epubjs themes）
- 文字大小調整

### epub.js Fork 修改重點

修改檔案：`frontend/src/lib/epubjs/managers/default/index.js`

1. **Scroll capping 修復**：`moveTo()` 會被 `scrollWidth` cap 住（字體載入前太小），增加 `_lastTarget` 在 `afterResized()` 重新 scroll
2. **Sub-pixel 修復**：`moveTo()` 的 `Math.floor` 加 3px tolerance
3. **Page-based restore**：CFI 的 `locationOf` 會因 character offset 精度不足導致 off-by-one，改用 `section_page` 直接計算 scroll offset

引入方式：`EpubReader.svelte` 使用 `import('$lib/epubjs/epub.js')` 直接引用本地 fork（Vite alias 無效）。

## Auth

- Token 存在 localStorage + cookie（非 httpOnly）
- `hooks.server.ts`：SSR 時讀 cookie → 呼叫 `/api/auth/me` 驗證 → 設 `locals.user`
- 未認證用戶 SSR 一律 redirect `/login`
- Client-side `client.ts`：API 回 401 → 清 localStorage + cookie → redirect `/login`

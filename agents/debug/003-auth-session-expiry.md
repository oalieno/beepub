# Debug: Auth Session 過期太快 + 過期後未跳轉登入頁

**日期**：2026-03  
**狀態**：✅ 已修復  
**影響檔案**：
- `backend/app/config.py`
- `.env.example`
- `.env`（需手動更新）
- `frontend/src/lib/api/client.ts`
- `frontend/src/hooks.server.ts`

---

## 問題描述

1. JWT token 預設 30 分鐘就過期，使用閱讀器時很快就被登出
2. Token 過期後，前端仍然顯示 navbar 和頁面框架，只是 API 呼叫失敗顯示 "Could not validate credentials" toast，需要手動按登出才會回到登入頁

## 根因

### Token 過期太快
- `backend/app/config.py` default 雖然設了 30 分鐘（後改為 10080）
- `.env` 和 `.env.example` 中 `ACCESS_TOKEN_EXPIRE_MINUTES=30` 覆蓋了 default

### 過期後未跳轉
- **Client-side**：`frontend/src/lib/api/client.ts` 收到 401 只拋出 Error，沒有清除 auth 狀態或跳轉
- **Server-side**：`frontend/src/hooks.server.ts` 驗證失敗時會清除 cookie，但只有首頁 (`+page.server.ts`) 有做 redirect，其他路由（libraries, books, admin 等）沒有 guard

## 修復

### 1. Token 過期延長到 7 天
```
ACCESS_TOKEN_EXPIRE_MINUTES=10080
```
更新 `backend/app/config.py`、`.env.example`，使用者需手動更新 `.env`。

### 2. Client-side 401 自動跳轉
`frontend/src/lib/api/client.ts` 加入：
```typescript
if (res.status === 401 && typeof window !== 'undefined') {
  localStorage.removeItem('token');
  localStorage.removeItem('user');
  document.cookie = 'token=; Max-Age=0; path=/';
  window.location.href = '/login';
}
```

### 3. Server-side 統一路由保護
`frontend/src/hooks.server.ts` 加入：
```typescript
const path = event.url.pathname;
if (!event.locals.user && path !== '/login') {
  throw redirect(302, '/login');
}
```
移除了各頁面獨立的 guard 需求，統一在 hooks 處理。

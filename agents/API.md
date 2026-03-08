# BeePub Backend API

## Auth
```
POST /api/auth/register   body:{username,email,password}
POST /api/auth/login      body:{username,password} → {access_token, token_type}
GET  /api/auth/me
```

## Libraries
```
GET    /api/libraries                    可見的圖書館列表（public + 白名單）
POST   /api/libraries                    [admin]
GET    /api/libraries/{id}
PUT    /api/libraries/{id}               [admin]
DELETE /api/libraries/{id}               [admin]
GET    /api/libraries/{id}/books         帶搜尋/排序
POST   /api/libraries/{id}/books         加入書籍 [admin]
DELETE /api/libraries/{id}/books/{bid}   [admin]
GET    /api/libraries/{id}/members       [admin] private 圖書館白名單
POST   /api/libraries/{id}/members       [admin]
DELETE /api/libraries/{id}/members/{uid} [admin]
```

## Books
```
GET    /api/books              全域搜尋（有權限存取的書）
POST   /api/books              上傳單本 epub（multipart）
POST   /api/books/bulk         上傳多本
GET    /api/books/{id}
PUT    /api/books/{id}/metadata 手動覆寫 metadata
DELETE /api/books/{id}         [admin]
GET    /api/books/{id}/file    串流 epub 檔案
GET    /api/books/{id}/cover
POST   /api/books/{id}/refresh 手動觸發 metadata 爬取
GET    /api/books/{id}/external 取得外部 metadata（評分書評）
```

## 使用者互動
```
PUT  /api/books/{id}/rating    body:{rating:1-5|null}
PUT  /api/books/{id}/favorite  body:{is_favorite:bool}
PUT  /api/books/{id}/reading-status body:{reading_status:str|null, started_at:date|null, finished_at:date|null}
PUT  /api/books/{id}/notes     body:{notes:str|null}
GET  /api/books/{id}/interaction → {rating, is_favorite, reading_progress, reading_status, started_at, finished_at, notes, updated_at}
GET  /api/books/{id}/progress
PUT  /api/books/{id}/progress  body:{cfi,percentage,current_page,section_page,...}
                               （同時累積閱讀秒數到 reading_activity）
GET  /api/books/{id}/highlights
POST /api/books/{id}/highlights body:{cfi_range,text,color,note?}
PUT  /api/books/{id}/highlights/{hid}
DELETE /api/books/{id}/highlights/{hid}
```

## 閱讀統計
```
GET  /api/books/reading-activity?year=2026  → [{date, seconds}, ...]
```

## Bookshelves
```
GET    /api/bookshelves
POST   /api/bookshelves
GET    /api/bookshelves/{id}
PUT    /api/bookshelves/{id}
DELETE /api/bookshelves/{id}
POST   /api/bookshelves/{id}/books    body:{book_id}
DELETE /api/bookshelves/{id}/books/{bid}
PUT    /api/bookshelves/{id}/books/reorder
```

## Admin
```
GET    /api/admin/users
PUT    /api/admin/users/{id}/role
DELETE /api/admin/users/{id}
GET    /api/admin/stats
```

## Admin — Calibre Import
```
GET  /api/admin/calibre/libraries                    掃描 /calibre/ 下可用的 Calibre library
POST /api/admin/calibre/libraries                    連結 Calibre library（建 BeePub library + sync）
POST /api/admin/calibre/libraries/{library_id}/sync  觸發 re-sync (202)
GET  /api/admin/calibre/libraries/{library_id}/status sync 進度 + 已匯入書數
```

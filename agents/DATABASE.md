# BeePub 資料庫 Schema

## users
```
id uuid PK | username varchar unique | email varchar unique
password_hash varchar | role enum(admin,user) | is_active bool | created_at
```

## libraries
```
id uuid PK | name varchar | description text | cover_image varchar
visibility enum(public,private) | created_by uuid→users | created_at
```

## library_access（private 圖書館白名單）
```
library_id uuid→libraries | user_id uuid→users | granted_by uuid→users | granted_at
PK(library_id, user_id)
```

## library_books
```
library_id uuid→libraries | book_id uuid→books | added_by uuid→users | added_at
PK(library_id, book_id)
```

## books
```
id uuid PK | file_path varchar | file_size bigint | format varchar
cover_path varchar
-- EPUB 原始 metadata
epub_title, epub_authors text[], epub_publisher, epub_language
epub_isbn, epub_description, epub_published_date
-- 手動覆寫（優先顯示）
title, authors text[], publisher, description, published_date
-- 計算欄位
display_title = COALESCE(title, epub_title)
display_authors = COALESCE(authors, epub_authors)
added_by uuid→users | added_at
```

## external_metadata
```
id uuid PK | book_id uuid→books | source enum(goodreads,readmoo,kobo_tw)
source_url varchar | rating numeric(3,2) | rating_count int
reviews jsonb [{author,content,rating,date}] | raw_data jsonb | fetched_at
UNIQUE(book_id, source)
```

## bookshelves
```
id uuid PK | user_id uuid→users | name varchar | description text
is_public bool | created_at
```

## bookshelf_books
```
bookshelf_id uuid | book_id uuid | sort_order int | added_at
PK(bookshelf_id, book_id)
```

## user_book_interactions
```
user_id uuid→users | book_id uuid→books
rating smallint (1-5, nullable) | is_favorite bool
reading_progress jsonb {cfi, percentage, current_page, section_page, section_index, total_pages, font_size, ...}
reading_status varchar(20) (want_to_read, currently_reading, read, did_not_finish, nullable)
started_at date (nullable) | finished_at date (nullable)
notes text (markdown, nullable)
updated_at
PK(user_id, book_id)
```

## reading_activity（閱讀時間統計，每日累積秒數）
```
user_id uuid→users | date date | seconds int (default 0)
PK(user_id, date)
```
每次儲存閱讀進度時，計算與上次 last_read_at 的時間差（< 5 分鐘視為同一 session），累加到當天的 seconds。

## highlights
```
id uuid PK | user_id uuid→users | book_id uuid→books
cfi_range varchar | text text | color varchar
note text (nullable) | created_at | updated_at
```

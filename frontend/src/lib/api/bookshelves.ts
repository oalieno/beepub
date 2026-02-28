import { get, post, put, del } from './client';
import type { BookshelfOut, BookOut } from '$lib/types';

export const bookshelvesApi = {
  list: (token: string) =>
    get('/bookshelves', token) as Promise<BookshelfOut[]>,

  get: (id: string, token: string) =>
    get(`/bookshelves/${id}`, token) as Promise<BookshelfOut>,

  create: (data: { name: string; description?: string; is_public?: boolean }, token: string) =>
    post('/bookshelves', data, token) as Promise<BookshelfOut>,

  update: (id: string, data: { name?: string; description?: string; is_public?: boolean }, token: string) =>
    put(`/bookshelves/${id}`, data, token) as Promise<BookshelfOut>,

  delete: (id: string, token: string) =>
    del(`/bookshelves/${id}`, token),

  getBooks: (id: string, token: string) =>
    get(`/bookshelves/${id}/books`, token) as Promise<BookOut[]>,

  addBook: (id: string, bookId: string, token: string) =>
    post(`/bookshelves/${id}/books`, { book_id: bookId }, token),

  removeBook: (id: string, bookId: string, token: string) =>
    del(`/bookshelves/${id}/books/${bookId}`, token),

  reorder: (id: string, bookIds: string[], token: string) =>
    put(`/bookshelves/${id}/books/reorder`, { book_ids: bookIds }, token),
};

export const adminApi = {
  getUsers: (token: string) =>
    get('/admin/users', token) as Promise<import('$lib/types').UserOut[]>,

  updateRole: (userId: string, role: string, token: string) =>
    put(`/admin/users/${userId}/role`, { role }, token),

  deleteUser: (userId: string, token: string) =>
    del(`/admin/users/${userId}`, token),

  getStats: (token: string) =>
    get('/admin/stats', token) as Promise<import('$lib/types').AdminStats>,
};

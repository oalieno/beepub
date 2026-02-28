import type { Handle } from '@sveltejs/kit';
import { env } from '$env/dynamic/private';

const BACKEND_URL = env.BACKEND_URL || 'http://backend:8000';

export const handle: Handle = async ({ event, resolve }) => {
  const token = event.cookies.get('token') ?? null;
  event.locals.token = token;
  event.locals.user = null;

  if (token) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        event.locals.user = await res.json();
      } else {
        event.cookies.delete('token', { path: '/' });
        event.locals.token = null;
      }
    } catch {
      event.cookies.delete('token', { path: '/' });
      event.locals.token = null;
    }
  }

  return resolve(event);
};

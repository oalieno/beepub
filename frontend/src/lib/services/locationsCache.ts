// IndexedDB cache for epub.js generated locations. Generating locations
// requires fetching and parsing every spine section, which takes seconds to
// tens of seconds for large books — but the result is deterministic per
// book file, so we compute once and reload afterwards.

const DB_NAME = "beepub-reader";
const STORE = "locations";
const MAX_ENTRIES = 40;

interface LocationsEntry {
  bookId: string;
  fingerprint: string;
  locations: string;
  savedAt: number;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: "bookId" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function requestToPromise<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function getCachedLocations(
  bookId: string,
): Promise<LocationsEntry | null> {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readonly");
    const entry = await requestToPromise(
      tx.objectStore(STORE).get(bookId) as IDBRequest<
        LocationsEntry | undefined
      >,
    );
    db.close();
    return entry ?? null;
  } catch {
    return null;
  }
}

export async function setCachedLocations(
  bookId: string,
  fingerprint: string,
  locations: string,
): Promise<void> {
  try {
    const db = await openDb();
    const tx = db.transaction(STORE, "readwrite");
    const store = tx.objectStore(STORE);
    store.put({
      bookId,
      fingerprint,
      locations,
      savedAt: Date.now(),
    } satisfies LocationsEntry);

    // Evict oldest entries beyond the cap so the cache doesn't grow forever.
    const all = await requestToPromise(
      store.getAll() as IDBRequest<LocationsEntry[]>,
    );
    if (all.length > MAX_ENTRIES) {
      all
        .sort((a, b) => a.savedAt - b.savedAt)
        .slice(0, all.length - MAX_ENTRIES)
        .forEach((entry) => store.delete(entry.bookId));
    }
    db.close();
  } catch {
    // Quota exceeded or private browsing — regenerate next time instead
  }
}

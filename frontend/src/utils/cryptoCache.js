const DB_NAME = 'securemsg-crypto-cache';
const DB_VERSION = 1;
const STORE_NAME = 'derived-keys';

let dbPromise = null;

function getDB() {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
  });

  return dbPromise;
}

const memoryCache = new Map();

export async function getCachedDerivedKey(cacheKey) {
  if (memoryCache.has(cacheKey)) {
    return memoryCache.get(cacheKey);
  }

  try {
    const db = await getDB();
    const transaction = db.transaction(STORE_NAME, 'readonly');
    const store = transaction.objectStore(STORE_NAME);
    const request = store.get(cacheKey);

    return new Promise((resolve, reject) => {
      request.onsuccess = () => {
        if (request.result) {
          memoryCache.set(cacheKey, request.result.key);
          resolve(request.result.key);
        } else {
          resolve(null);
        }
      };
      request.onerror = () => reject(request.error);
    });
  } catch {
    return null;
  }
}

export async function setCachedDerivedKey(cacheKey, key) {
  memoryCache.set(cacheKey, key);

  try {
    const db = await getDB();
    const transaction = db.transaction(STORE_NAME, 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    store.put({ id: cacheKey, key, timestamp: Date.now() });
  } catch {
    // Ignore IndexedDB errors, memory cache still works
  }
}

export function clearMemoryCache() {
  memoryCache.clear();
}

export async function clearIndexedDBCache() {
  try {
    const db = await getDB();
    const transaction = db.transaction(STORE_NAME, 'readwrite');
    const store = transaction.objectStore(STORE_NAME);
    store.clear();
  } catch {
    // Ignore
  }
  clearMemoryCache();
}

export function createCacheKey(password, salt) {
  return `derived:${btoa(String.fromCharCode(...password))}:${btoa(String.fromCharCode(...salt))}`;
}
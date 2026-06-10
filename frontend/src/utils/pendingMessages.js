const STORAGE_KEY = "pendingMessages";

export function getPendingMessages() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return [];
  }
}

export function savePendingMessage(msg) {
  const list = getPendingMessages();
  list.push(msg);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

export function removePendingMessage(id) {
  const list = getPendingMessages().filter((m) => m.pendingId !== id);
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

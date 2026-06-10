const DB_NAME = 'securemsg-offline';
const DB_VERSION = 1;
const STORES = {
  messages: 'pending-messages',
  reactions: 'pending-reactions',
  reads: 'pending-reads',
};

let dbPromise = null;

function getDB() {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);

    request.onupgradeneeded = (event) => {
      const db = event.target.result;
      Object.values(STORES).forEach((storeName) => {
        if (!db.objectStoreNames.contains(storeName)) {
          db.createObjectStore(storeName, { keyPath: 'id', autoIncrement: true });
        }
      });
    };
  });

  return dbPromise;
}

export async function queueMessage(message) {
  const db = await getDB();
  const transaction = db.transaction(STORES.messages, 'readwrite');
  const store = transaction.objectStore(STORES.messages);
  store.add({ ...message, timestamp: Date.now() });
  return transaction.done;
}

export async function getPendingMessages() {
  const db = await getDB();
  const transaction = db.transaction(STORES.messages, 'readonly');
  const store = transaction.objectStore(STORES.messages);
  const request = store.getAll();
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

export async function removePendingMessage(id) {
  const db = await getDB();
  const transaction = db.transaction(STORES.messages, 'readwrite');
  const store = transaction.objectStore(STORES.messages);
  store.delete(id);
  return transaction.done;
}

export async function queueReaction(reaction) {
  const db = await getDB();
  const transaction = db.transaction(STORES.reactions, 'readwrite');
  const store = transaction.objectStore(STORES.reactions);
  store.add({ ...reaction, timestamp: Date.now() });
  return transaction.done;
}

export async function getPendingReactions() {
  const db = await getDB();
  const transaction = db.transaction(STORES.reactions, 'readonly');
  const store = transaction.objectStore(STORES.reactions);
  const request = store.getAll();
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

export async function removePendingReaction(id) {
  const db = await getDB();
  const transaction = db.transaction(STORES.reactions, 'readwrite');
  const store = transaction.objectStore(STORES.reactions);
  store.delete(id);
  return transaction.done;
}

export async function queueRead(read) {
  const db = await getDB();
  const transaction = db.transaction(STORES.reads, 'readwrite');
  const store = transaction.objectStore(STORES.reads);
  store.add({ ...read, timestamp: Date.now() });
  return transaction.done;
}

export async function getPendingReads() {
  const db = await getDB();
  const transaction = db.transaction(STORES.reads, 'readonly');
  const store = transaction.objectStore(STORES.reads);
  const request = store.getAll();
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

export async function removePendingRead(id) {
  const db = await getDB();
  const transaction = db.transaction(STORES.reads, 'readwrite');
  const store = transaction.objectStore(STORES.reads);
  store.delete(id);
  return transaction.done;
}

export async function syncPendingData(api) {
  const [messages, reactions, reads] = await Promise.all([
    getPendingMessages(),
    getPendingReactions(),
    getPendingReads(),
  ]);

  for (const msg of messages) {
    try {
      await api.sendMessage(msg.receiver_id, msg.encrypted_content, msg.attachment_ids);
      await removePendingMessage(msg.id);
    } catch {
      // Keep in queue for next sync
    }
  }

  for (const reaction of reactions) {
    try {
      await api.addReaction(reaction.message_id, reaction.emoji);
      await removePendingReaction(reaction.id);
    } catch {
      // Keep in queue
    }
  }

  for (const read of reads) {
    try {
      await api.markRead(read.user_id);
      await removePendingRead(read.id);
    } catch {
      // Keep in queue
    }
  }
}
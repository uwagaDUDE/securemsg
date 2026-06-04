const CRYPTO = {
    isAvailable() {
        return typeof crypto !== "undefined" && crypto.subtle !== undefined;
    },
    async generateKeys(password) {
        const rsaKeyPair = await crypto.subtle.generateKey(
            {
                name: "RSA-OAEP",
                modulusLength: 2048,
                publicExponent: new Uint8Array([1, 0, 1]),
                hash: "SHA-256",
            },
            true,
            ["encrypt", "decrypt"]
        );

        const broadcastKey = await crypto.subtle.generateKey(
            { name: "AES-CBC", length: 256 },
            true,
            ["encrypt", "decrypt"]
        );

        const publicKeySpki = await crypto.subtle.exportKey("spki", rsaKeyPair.publicKey);
        const privateKeyPkcs8 = await crypto.subtle.exportKey("pkcs8", rsaKeyPair.privateKey);
        const broadcastKeyRaw = await crypto.subtle.exportKey("raw", broadcastKey);

        const salt = crypto.getRandomValues(new Uint8Array(16));
        const iv = crypto.getRandomValues(new Uint8Array(12));
        const derivedKey = await this._deriveKey(password, salt);
        const encryptedPrivateKey = await crypto.subtle.encrypt(
            { name: "AES-GCM", iv },
            derivedKey,
            privateKeyPkcs8
        );

        const encPrivateKeyBlob = new Uint8Array(salt.length + iv.length + encryptedPrivateKey.byteLength);
        encPrivateKeyBlob.set(salt, 0);
        encPrivateKeyBlob.set(iv, salt.length);
        encPrivateKeyBlob.set(new Uint8Array(encryptedPrivateKey), salt.length + iv.length);

        return {
            publicKey: new Uint8Array(publicKeySpki),
            encryptedPrivateKey: encPrivateKeyBlob,
            broadcastKey: new Uint8Array(broadcastKeyRaw),
        };
    },

    async decryptPrivateKey(encryptedPrivateKeyBlob, password) {
        const blob = new Uint8Array(encryptedPrivateKeyBlob);
        const salt = blob.slice(0, 16);
        const iv = blob.slice(16, 28);
        const data = blob.slice(28);

        const derivedKey = await this._deriveKey(password, salt);
        const pkcs8 = await crypto.subtle.decrypt(
            { name: "AES-GCM", iv },
            derivedKey,
            data
        );

        return await crypto.subtle.importKey(
            "pkcs8",
            pkcs8,
            { name: "RSA-OAEP", hash: "SHA-256" },
            false,
            ["decrypt"]
        );
    },

    async importPublicKey(spkiBytes) {
        return await crypto.subtle.importKey(
            "spki",
            spkiBytes,
            { name: "RSA-OAEP", hash: "SHA-256" },
            true,
            ["encrypt"]
        );
    },

    async importBroadcastKey(rawBytes) {
        return await crypto.subtle.importKey(
            "raw",
            rawBytes,
            { name: "AES-CBC", length: 256 },
            false,
            ["encrypt", "decrypt"]
        );
    },

    async encryptMessage(plaintext, broadcastKey) {
        const iv = crypto.getRandomValues(new Uint8Array(16));
        const encoded = new TextEncoder().encode(plaintext);
        const ciphertext = await crypto.subtle.encrypt(
            { name: "AES-CBC", iv },
            broadcastKey,
            encoded
        );
        const combined = new Uint8Array(iv.length + ciphertext.byteLength);
        combined.set(iv, 0);
        combined.set(new Uint8Array(ciphertext), iv.length);
        return btoa(String.fromCharCode(...combined));
    },

    async decryptMessage(encryptedBase64, broadcastKey) {
        try {
            const combined = Uint8Array.from(atob(encryptedBase64), (c) => c.charCodeAt(0));
            const iv = combined.slice(0, 16);
            const data = combined.slice(16);
            const decrypted = await crypto.subtle.decrypt(
                { name: "AES-CBC", iv },
                broadcastKey,
                data
            );
            return new TextDecoder().decode(decrypted);
        } catch {
            return null;
        }
    },

    async encryptBinary(data, broadcastKey) {
        const iv = crypto.getRandomValues(new Uint8Array(16));
        const ciphertext = await crypto.subtle.encrypt(
            { name: "AES-CBC", iv },
            broadcastKey,
            data
        );
        const combined = new Uint8Array(iv.length + ciphertext.byteLength);
        combined.set(iv, 0);
        combined.set(new Uint8Array(ciphertext), iv.length);
        return combined;
    },

    async decryptBinary(encryptedData, broadcastKey) {
        const iv = encryptedData.slice(0, 16);
        const data = encryptedData.slice(16);
        return new Uint8Array(await crypto.subtle.decrypt(
            { name: "AES-CBC", iv },
            broadcastKey,
            data
        ));
    },

    async encryptBroadcastKey(broadcastKeyRaw, targetPublicKeySpki) {
        const pubKey = await this.importPublicKey(targetPublicKeySpki);
        const encrypted = await crypto.subtle.encrypt(
            { name: "RSA-OAEP" },
            pubKey,
            broadcastKeyRaw
        );
        return new Uint8Array(encrypted);
    },

    async decryptBroadcastKey(encryptedKey, privateKey) {
        const decrypted = await crypto.subtle.decrypt(
            { name: "RSA-OAEP" },
            privateKey,
            encryptedKey
        );
        return new Uint8Array(decrypted);
    },

    getErrorMessage() {
        if (!this.isAvailable()) {
            if (location.protocol === "http:" && location.hostname !== "localhost" && location.hostname !== "127.0.0.1") {
                return "Web Crypto API requires HTTPS. Open the app via https:// or localhost.";
            }
            return "Web Crypto API is not available in this browser.";
        }
        return null;
    },

    _deriveKey(password, salt) {
        const enc = new TextEncoder();
        return crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]).then(
            (key) =>
                crypto.subtle.deriveKey(
                    { name: "PBKDF2", salt, iterations: 600000, hash: "SHA-256" },
                    key,
                    { name: "AES-GCM", length: 256 },
                    false,
                    ["encrypt", "decrypt"]
                )
        );
    },
};

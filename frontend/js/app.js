(function () {
    console.log("[app] loaded, io defined:", typeof io !== "undefined", "token:", !!localStorage.getItem("token"), "user_id:", localStorage.getItem("user_id"));
    const $ = (id) => document.getElementById(id);

    let refreshLock = null;

    async function refreshToken() {
        if (refreshLock) return refreshLock;
        var token = localStorage.getItem('token');
        if (!token) { console.log("[refreshToken] no token in storage"); return null; }
        console.log("[refreshToken] attempting refresh...");
        refreshLock = (async function () {
            try {
                var res = await fetch('/api/auth/refresh', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token },
                });
                console.log("[refreshToken] status:", res.status);
                if (!res.ok) {
                    try { console.log("[refreshToken] body:", await res.text()); } catch (_) {}
                    return null;
                }
                var data = await res.json();
                localStorage.setItem('token', data.token);
                localStorage.setItem('user_id', data.user_id);
                appToken = data.token;
                console.log('[auth] token refreshed OK, new user_id:', data.user_id);
                return data.token;
            } catch (e) {
                console.error("[refreshToken] fetch error:", e.message || e);
                return null;
            } finally {
                refreshLock = null;
            }
        })();
        return refreshLock;
    }

    async function apiFetch(url, options) {
        options = options || {};
        options.headers = options.headers || {};
        if (!options.headers['Authorization']) {
            options.headers['Authorization'] = 'Bearer ' + (appToken || localStorage.getItem('token'));
        }
        console.log("[apiFetch] ->", url);
        var res = await fetch(url, options);
        console.log("[apiFetch] <-", url, "status:", res.status);
        if (res.status === 401 || res.status === 403) {
            console.warn("[apiFetch] 401/403 on", url, "— trying token refresh");
            var newToken = await refreshToken();
            if (newToken) {
                options.headers['Authorization'] = 'Bearer ' + newToken;
                console.log("[apiFetch] retrying", url, "with new token");
                res = await fetch(url, options);
                console.log("[apiFetch] retry <-", url, "status:", res.status);
                if (res.status !== 401 && res.status !== 403) return res;
            }
            console.error("[apiFetch] session dead — reloading page");
            localStorage.clear();
            sessionStorage.clear();
            location.reload();
            throw new Error("Session expired");
        }
        return res;
    }

    function redirectOnAuthError(res) {
        // legacy — kept for compatibility, but apiFetch handles it now
        if (res.status === 401 || res.status === 403) {
            refreshToken().then(function (newToken) {
                if (!newToken) {
                    localStorage.clear();
                    sessionStorage.clear();
                }
                location.reload();
            });
            return true;
        }
        return false;
    }

    let currentUser = null;
    let privateKey = null;
    let myBroadcastKey = null;
    let broadcastKeyCache = {};
    let activeChatId = null;
    let activeChatEl = null;
    let typingTimer = null;
    let readThrottle = {};
    let unreadCounts = {};
    let appToken = null;
    let userCache = {};
    let notificationsEnabled = localStorage.getItem('notifications') !== 'false';
    let replyTo = null;
    let contextMenuTarget = null;
    let pendingImages = [];  // [{ dataURL, mime, compressedSize, originalSize }]
    let storedPassword = null;
    let activeChannelId = null;
    let activeGroupId = null;
    let groupKeyCache = {};  // { "g:ownerId": CryptoKey } for group broadcast keys

    function b64enc(buf) {
        return btoa(String.fromCharCode(...new Uint8Array(buf)));
    }
    function b64dec(str) {
        return Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
    }
    function avatarLetter(name) {
        return name.charAt(0).toUpperCase();
    }
    function escHtml(s) {
        const d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    // ── image compression ──
    function compressImage(file) {
        return new Promise(function (resolve) {
            var maxDim = 800;
            var quality = 0.45;
            var img = new Image();
            var url = URL.createObjectURL(file);
            img.onload = function () {
                URL.revokeObjectURL(url);
                var w = img.width, h = img.height;
                if (w > maxDim || h > maxDim) {
                    var ratio = Math.min(maxDim / w, maxDim / h);
                    w = Math.round(w * ratio);
                    h = Math.round(h * ratio);
                }
                var canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                var ctx = canvas.getContext('2d');
                ctx.drawImage(img, 0, 0, w, h);
                canvas.toBlob(function (blob) {
                    var reader = new FileReader();
                    reader.onloadend = function () {
                        resolve({
                            dataURL: reader.result,
                            mime: 'image/jpeg',
                            compressedSize: blob.size,
                            originalSize: file.size
                        });
                    };
                    reader.readAsDataURL(blob);
                }, 'image/jpeg', quality);
            };
            img.src = url;
        });
    }

    function renderPreview() {
        var area = $('preview-area');
        area.innerHTML = '';
        if (pendingImages.length === 0) {
            area.classList.add('hidden');
            return;
        }
        area.classList.remove('hidden');
        pendingImages.forEach(function (img, idx) {
            var div = document.createElement('div');
            div.className = 'preview-item';
            var el = document.createElement('img');
            el.src = img.dataURL;
            div.appendChild(el);
            var rm = document.createElement('button');
            rm.className = 'preview-remove';
            rm.textContent = '✕';
            rm.onclick = function (e) { e.stopPropagation(); removeImage(idx); };
            div.appendChild(rm);
            if (pendingImages.length > 1) {
                var cnt = document.createElement('span');
                cnt.className = 'preview-counter';
                cnt.textContent = (idx + 1) + '/' + pendingImages.length;
                div.appendChild(cnt);
            }
            area.appendChild(div);
        });
    }

    function removeImage(idx) {
        pendingImages.splice(idx, 1);
        renderPreview();
    }

    window.handleFileSelect = function (e) {
        addImages(e.target.files);
        e.target.value = '';
    };

    function addImages(fileList) {
        if (!fileList || fileList.length === 0) return;
        var remaining = 10 - pendingImages.length;
        if (remaining <= 0) return;
        var files = Array.prototype.slice.call(fileList, 0, remaining);
        files.forEach(function (f) {
            if (!f.type.match(/image\/(jpeg|png|gif|webp)/)) return;
            if (f.size > 20 * 1024 * 1024) return; // skip >20MB originals
        });
        var promises = files.filter(Boolean).map(function (f) { return compressImage(f); });
        Promise.all(promises).then(function (results) {
            results.forEach(function (r) { pendingImages.push(r); });
            renderPreview();
        });
    }

    async function uploadImages() {
        if (pendingImages.length === 0) return [];
        var token = localStorage.getItem('token');
        var batch = pendingImages.map(function (img) {
            return CRYPTO.encryptBinary(b64dec(img.dataURL.split(',')[1]), myBroadcastKey).then(function (enc) {
                return {
                    data: b64enc(enc),
                    mime: img.mime,
                    original_size: img.originalSize,
                    compressed_size: img.compressedSize
                };
            });
        });
        var bodies = await Promise.all(batch);
        var res = await apiFetch('/api/attachments/upload', {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + token,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(bodies),
        });
        if (!res.ok) throw new Error('Upload failed');
        var data = await res.json();
        pendingImages = [];
        renderPreview();
        return data.ids || [];
    }

    async function fetchAndDecryptImage(attId, decryptKey) {
        if (!decryptKey) return null;
        var token = localStorage.getItem('token');
        var res = await apiFetch('/api/attachments/' + attId, {
            headers: { 'Authorization': 'Bearer ' + token },
        });
        if (!res.ok) return null;
        var blob = await res.arrayBuffer();
        try {
            var dec = await CRYPTO.decryptBinary(new Uint8Array(blob), decryptKey);
            var b64 = btoa(String.fromCharCode.apply(null, dec));
            return 'data:image/jpeg;base64,' + b64;
        } catch (_) {
            return null;
        }
    }

    window.openImageViewer = function (src) {
        $('image-viewer-img').src = src;
        $('image-viewer').classList.remove('hidden');
    };

    window.closeImageViewer = function () {
        $('image-viewer').classList.add('hidden');
        $('image-viewer-img').src = '';
    };
    function updateTitle(senderName) {
        const total = Object.values(unreadCounts).reduce((a, b) => a + b, 0);
        if (total === 0) {
            document.title = "Secure Messenger";
        } else if (senderName && total === 1) {
            document.title = `(${total}) ${senderName} • Messenger`;
        } else {
            document.title = `(${total}) Messenger`;
        }
    }
    async function parseError(res) {
        try {
            const json = await res.json();
            return json.detail || json.message || `Error ${res.status}`;
        } catch {
            const text = await res.text();
            return text || `Error ${res.status}`;
        }
    }
    function flash(el) {
        el.style.animation = "none";
        el.offsetHeight;
        el.style.animation = "highlight 0.6s ease";
    }

    // ── tab switching ──
    window.switchTab = function (tab) {
        document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach((c) => c.classList.add("hidden"));
        var tabBtn = document.getElementById(`tab-${tab}`);
        if (tabBtn) tabBtn.classList.add("active");
        var tabContent = document.getElementById(`tab-content-${tab}`);
        if (tabContent) tabContent.classList.remove("hidden");
        if (tab === "invites") loadIncomingRequests();
        if (tab === "channels") loadChannels();
        if (tab === "blocked") loadBlocked();
    };

    // ── page switching ──
    window.showPage = function (id) {
        document.querySelectorAll(".auth-page, #main-page").forEach((p) => {
            if (p.id === id) {
                p.classList.remove("hidden");
                p.style.animation = "none";
                p.offsetHeight;
                p.style.animation = "fadeIn 0.3s ease";
            } else {
                p.classList.add("hidden");
            }
        });
    };

    window.toggleSidebar = function() {
        const sidebar = document.querySelector('.sidebar');
        const hamburger = document.getElementById('hamburger-btn');

        if (window.innerWidth <= 860) {
            // Mobile: drawer overlay behavior
            const backdrop = document.getElementById('sidebar-backdrop');
            const isOpen = sidebar.classList.contains('open');
            if (isOpen) {
                sidebar.classList.remove('open');
                backdrop.classList.remove('visible');
            } else {
                sidebar.classList.add('open');
                backdrop.classList.add('visible');
            }
        } else {
            // Desktop: collapse sidebar
            const isCollapsed = sidebar.classList.contains('collapsed');
            if (isCollapsed) {
                sidebar.classList.remove('collapsed');
                hamburger.classList.remove('desktop-show');
            } else {
                sidebar.classList.add('collapsed');
                hamburger.classList.add('desktop-show');
            }
        }
    };

    window.goBackToSidebar = function() {
        if (window.innerWidth <= 860) {
            document.querySelector('.sidebar').classList.add('open');
            document.getElementById('sidebar-backdrop').classList.add('visible');
            $('chat-header').classList.add('hidden');
            $('chat-area').classList.add('hidden');
            $('no-chat').classList.remove('hidden');
        }
        activeChatId = null;
    };

    // ── REGISTER ──
    window.handleRegister = async function () {
        const username = $("reg-username").value.trim();
        const password = $("reg-password").value;
        const errEl = $("reg-error");
        const btn = $("reg-btn");
        const loading = $("reg-loading");

        errEl.classList.add("hidden");

        const cryptoErr = CRYPTO.getErrorMessage();
        if (cryptoErr) {
            errEl.textContent = cryptoErr;
            errEl.classList.remove("hidden");
            return;
        }

        if (!username || !password) {
            errEl.textContent = "Fill in all fields";
            errEl.classList.remove("hidden");
            return;
        }
        if (password.length < 4) {
            errEl.textContent = "Password must be at least 4 characters";
            errEl.classList.remove("hidden");
            return;
        }

        btn.disabled = true;
        loading.classList.remove("hidden");

        try {
            const keys = await CRYPTO.generateKeys(password);
            const res = await fetch("/api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    username,
                    password,
                    public_key: b64enc(keys.publicKey),
                    encrypted_private_key: b64enc(keys.encryptedPrivateKey),
                    broadcast_key: b64enc(keys.broadcastKey),
                }),
            });
            if (!res.ok) {
                throw new Error(await parseError(res));
            }
            btn.disabled = false;
            loading.classList.add("hidden");
            $("login-username").value = username;
            $("login-password").value = "";
            showPage("login-page");
        } catch (e) {
            btn.disabled = false;
            loading.classList.add("hidden");
            errEl.textContent = e.message;
            errEl.classList.remove("hidden");
        }
    };

    // ── LOGIN ──
    window.handleLogin = async function () {
        const username = $("login-username").value.trim();
        const password = $("login-password").value;
        const errEl = $("login-error");
        const btn = $("login-btn");

        errEl.classList.add("hidden");

        const cryptoErr = CRYPTO.getErrorMessage();
        if (cryptoErr) {
            errEl.textContent = cryptoErr;
            errEl.classList.remove("hidden");
            return;
        }

        if (!username || !password) {
            errEl.textContent = "Fill in all fields";
            errEl.classList.remove("hidden");
            return;
        }

        btn.disabled = true;
        try {
            const res = await fetch("/api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            if (!res.ok) {
                throw new Error(await parseError(res));
            }
            const data = await res.json();
            localStorage.setItem("token", data.token);
            localStorage.setItem("user_id", data.user_id);
            localStorage.setItem("username", data.username);
            localStorage.removeItem("password");
            storedPassword = password;
            await initApp(data.token);
        } catch (e) {
            btn.disabled = false;
            errEl.textContent = e.message;
            errEl.classList.remove("hidden");
        }
    };

    window.handleLogout = function () {
        MESSENGER_SOCKET.setOnlineStatus(false);
        MESSENGER_SOCKET.disconnect();
        localStorage.clear();
        sessionStorage.clear();
        location.reload();
    };

    // ── Visibility tracking (online/offline) ──
    function initVisibilityTracking() {
        function handleVisibilityChange() {
            if (document.visibilityState === 'visible') {
                MESSENGER_SOCKET.setOnlineStatus(true);
            } else {
                MESSENGER_SOCKET.setOnlineStatus(false);
            }
        }
        document.addEventListener('visibilitychange', handleVisibilityChange);

        // Clean up stale sidebar classes on resize
        let lastWidth = window.innerWidth;
        window.addEventListener('resize', function () {
            const w = window.innerWidth;
            const crossed = (lastWidth > 860 && w <= 860) || (lastWidth <= 860 && w > 860);
            if (crossed) {
                const sidebar = document.querySelector('.sidebar');
                const hamburger = document.getElementById('hamburger-btn');
                const backdrop = document.getElementById('sidebar-backdrop');
                if (w <= 860) {
                    sidebar.classList.remove('collapsed');
                    hamburger.classList.remove('desktop-show');
                } else {
                    sidebar.classList.remove('open');
                    if (backdrop) backdrop.classList.remove('visible');
                }
            }
            lastWidth = w;
        });

        window.addEventListener('pagehide', function () {
            MESSENGER_SOCKET.setOnlineStatus(false);
        });
    }

    // ── notifications ──
    function initNotifications() {
        if (!('Notification' in window)) {
            console.log("[notif] Notification API not available");
            return;
        }
        console.log("[notif] init, permission:", Notification.permission, "enabled:", notificationsEnabled);
        if (notificationsEnabled && Notification.permission === 'default') {
            try {
                Notification.requestPermission().then(function (perm) {
                    console.log("[notif] permission result:", perm);
                });
            } catch (e) {
                console.warn("[notif] requestPermission failed:", e);
            }
        }
    }

    async function setupPushNotifications(token) {
        console.log("[push] setting up...");

        if (!('serviceWorker' in navigator)) {
            console.log("[push] serviceWorker not supported");
            return;
        }
        if (!('PushManager' in window)) {
            console.log("[push] PushManager not supported");
            return;
        }

        try {
            var reg = await navigator.serviceWorker.register('/sw.js', { scope: '/' });
            await reg.update();
            console.log("[push] service worker registered, scope:", reg.scope);

            var vapidRes = await apiFetch('/api/push/vapid-public-key');
            var vapidData = await vapidRes.json();
            console.log("[push] got VAPID key, length:", vapidData.public_key.length);

            var sub = await reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: urlB64ToUint8Array(vapidData.public_key),
            });
            console.log("[push] pushManager.subscribe OK, endpoint:", sub.endpoint.substring(0, 60) + "...");

            var rawKey = sub.getKey('p256dh');
            var rawAuth = sub.getKey('auth');
            var p256dh = rawKey ? btoa(String.fromCharCode.apply(null, new Uint8Array(rawKey))) : '';
            var auth = rawAuth ? btoa(String.fromCharCode.apply(null, new Uint8Array(rawAuth))) : '';

            await apiFetch('/api/push/subscribe', {
                method: 'POST',
                headers: {
                    'Authorization': 'Bearer ' + token,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    endpoint: sub.endpoint,
                    p256dh: p256dh,
                    auth: auth,
                }),
            });
            console.log("[push] subscription saved to server");

            if (!notificationsEnabled) {
                notificationsEnabled = true;
                localStorage.setItem('notifications', 'true');
                updateNotificationButton();
                console.log("[push] notificationsEnabled forced to true");
            }
            if (Notification.permission === 'default') {
                var perm = await Notification.requestPermission();
                console.log("[push] notification permission:", perm);
            }
        } catch (e) {
            console.error("[push] FAILED:", e.message || e, e);
        }
    }

    function urlB64ToUint8Array(base64String) {
        var padding = '='.repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        var rawData = window.atob(base64);
        var outputArray = new Uint8Array(rawData.length);
        for (var i = 0; i < rawData.length; ++i) {
            outputArray[i] = rawData.charCodeAt(i);
        }
        return outputArray;
    }

    function showObfuscatedNotification(senderName) {
        console.log("[notif] triggered, notificationsEnabled:", notificationsEnabled,
            "permission:", Notification.permission,
            "visible:", document.visibilityState,
            "focused:", document.hasFocus());

        if (!notificationsEnabled) {
            console.log("[notif] skipped — notifications disabled in app");
            return;
        }

        const body = senderName ? `New message from ${senderName}` : 'You have a new message';

        if (document.visibilityState === 'visible' && document.hasFocus()) {
            showToast(body);
            console.log("[notif] toast shown (page visible + focused)");
            return;
        }

        if ('Notification' in window && Notification.permission === 'granted') {
            try {
                new Notification('Secure Messenger', {
                    body: body,
                    icon: '/favicon.png',
                    tag: 'securemsg',
                });
                console.log("[notif] browser notification shown");
            } catch (e) {
                console.error("[notif] browser notification failed:", e);
            }
        } else {
            console.log("[notif] no browser notification — permission:", Notification.permission);
        }
    }

    let toastTimer = null;
    function showToast(text) {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = text;
        toast.classList.remove('hidden');
        toast.style.animation = 'none';
        toast.offsetHeight;
        toast.style.animation = 'toastIn 0.3s ease';
        clearTimeout(toastTimer);
        toastTimer = setTimeout(function () {
            toast.classList.add('hidden');
        }, 4000);
    }

    window.toggleNotifications = async function() {
        if (!('Notification' in window)) {
            alert('Notifications not supported');
            return;
        }
        if (Notification.permission === 'denied') {
            alert('Notifications blocked by browser. Please enable in browser settings.');
            return;
        }
        notificationsEnabled = !notificationsEnabled;
        localStorage.setItem('notifications', notificationsEnabled);
        if (notificationsEnabled && Notification.permission === 'default') {
            await Notification.requestPermission();
        }
        updateNotificationButton();
    };

    function updateNotificationButton() {
        const btn = $('notif-toggle');
        if (!btn) return;
        btn.textContent = notificationsEnabled ? '🔔' : '🔕';
        btn.title = notificationsEnabled ? 'Disable notifications' : 'Enable notifications';
    }

    // ── initialise app after login ──
    async function initApp(token) {
        console.log("[initApp] start, token len:", token ? token.length : 0);
        appToken = token;
        const res = await apiFetch("/api/auth/me", {
            headers: { Authorization: `Bearer ${token}` },
        });
        currentUser = await res.json();
        console.log("[initApp] /auth/me OK, user:", currentUser.id, currentUser.username,
            "hasBroadcastKey:", !!currentUser.broadcast_key,
            "hasEncPrivKey:", !!currentUser.encrypted_private_key);

        const storedPass = storedPassword || sessionStorage.getItem("password") || localStorage.getItem("password");
        console.log("[initApp] storedPass:", !!storedPass);
        if (storedPass && storedPass === localStorage.getItem("password")) {
            storedPassword = storedPass;
            localStorage.removeItem("password");
        }
        if (storedPass && storedPass === sessionStorage.getItem("password")) {
            storedPassword = storedPass;
            sessionStorage.removeItem("password");
        }

        if (currentUser.encrypted_private_key && storedPass) {
            try {
                const encBlob = b64dec(currentUser.encrypted_private_key);
                privateKey = await CRYPTO.decryptPrivateKey(encBlob, storedPass);
                console.log("[initApp] privateKey decrypted OK");
            } catch (e) {
                console.error("[initApp] decrypt private key failed:", e);
            }
        }
        if (currentUser.broadcast_key) {
            myBroadcastKey = await CRYPTO.importBroadcastKey(b64dec(currentUser.broadcast_key));
            console.log("[initApp] myBroadcastKey imported OK");
        } else {
            console.warn("[initApp] NO broadcast_key in currentUser!");
        }

        showPage("main-page");
        $("user-greeting").textContent = currentUser.username;
        console.log("[initApp] loading users...");
        await loadUsers();
        await fetchUnreadCounts();
        loadIncomingRequests();
        connectSocket(token);
        initVisibilityTracking();
        initNotifications();
        updateNotificationButton();
        setupPushNotifications(token);
        console.log("[initApp] === DONE ===");
    }

    function addSystemMessage(text) {
        const container = $("messages");
        if (!container) return;
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = text;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    async function refreshKeyStatusFor(userId) {
        if (!userId || $("chat-revoke-btn").classList.contains("hidden")) return;
        const token = localStorage.getItem("token");
        try {
            const [myKeyRes, theirKeyRes] = await Promise.all([
                apiFetch(`/api/messages/${userId}/has-my-key`, { headers: { Authorization: `Bearer ${token}` } }),
                apiFetch(`/api/messages/${userId}/shared-key`, { headers: { Authorization: `Bearer ${token}` } }),
            ]);
            const isMyKeyShared = await myKeyRes.json();
            const theirKey = await theirKeyRes.json();
            const hasTheirKey = !!(theirKey && theirKey.encrypted_broadcast_key);

            $("chat-revoke-btn").textContent = isMyKeyShared ? "🔑" : "🔒";
            $("chat-revoke-btn").title = isMyKeyShared ? "Revoke your key" : "Share your key";
            $("chat-key-status").textContent = isMyKeyShared
                ? "✓ Key shared"
                : "✗ Key not shared";

            if (hasTheirKey) {
                $("chat-request-key-btn").classList.add("hidden");
            } else {
                $("chat-request-key-btn").classList.remove("hidden");
                $("chat-request-key-btn").onclick = () => requestKeyAccess(userId);
            }
        } catch (e) {
            console.error("refreshKeyStatusFor failed:", e);
        }
    }

    // ── socket ──
    function connectSocket(token) {
        console.log("[connectSocket] connecting with token len:", token ? token.length : 0);
        MESSENGER_SOCKET.connect(token, {
            onConnect: () => {
                console.log("[connectSocket] socket (re)connected, re-joining activeChat:", activeChatId);
                if (activeChatId) {
                    MESSENGER_SOCKET.joinRoom(activeChatId);
                }
            },
            onMessage: handleIncomingMessage,
            onTyping: handleTypingIndicator,
            onKeyShared: async ({ owner_id }) => {
                await loadSharedKey(owner_id);
                if (owner_id === activeChatId) {
                    await renderMessages(owner_id);
                }
                await refreshKeyStatusFor(owner_id);
            },
            onKeyRevoked: async ({ owner_id }) => {
                delete broadcastKeyCache[owner_id];
                if (activeChatId === owner_id) {
                    await renderMessages(owner_id);
                    await refreshKeyStatusFor(owner_id);
                }
            },
            onPermissionRequest: async () => {
                await loadIncomingRequests();
                flash($("tab-invites"));
            },
            onPermissionResponse: async (data) => {
                await loadUsers();
                if (data.status === "approved" && activeChatId === data.owner_id) {
                    await loadSharedKey(data.owner_id);
                }
            },
            onKeyRequested: async (data) => {
                if (activeChatId === data.requester_id) {
                    await renderMessages(activeChatId);
                }
            },
            onUserStatus: (data) => {
                if (userCache[data.user_id]) {
                    userCache[data.user_id].is_online = data.is_online;
                    userCache[data.user_id].last_seen = data.last_seen;
                }
                const item = document.querySelector(`.user-item[data-user-id="${data.user_id}"]`);
                if (item) {
                    const avatar = item.querySelector('.user-avatar');
                    let dot = avatar?.querySelector('.online-dot');
                    if (data.is_online && !dot) {
                        const newDot = document.createElement('span');
                        newDot.className = 'online-dot';
                        avatar?.appendChild(newDot);
                    } else if (!data.is_online && dot) {
                        dot.remove();
                    }
                }
                if (activeChatId === data.user_id) {
                    // could update a status line under chat name
                }
            },
            onMessageEdited: (data) => {
                const el = document.querySelector(`.message[data-msg-id="${data.message_id}"]`);
                if (el) {
                    const textEl = el.querySelector('.message-text');
                    if (textEl && data.encrypted_content) {
                        if (myBroadcastKey) {
                            CRYPTO.decryptMessage(data.encrypted_content, myBroadcastKey).then(function (txt) {
                                textEl.textContent = txt;
                            });
                        }
                    }
                    if (textEl && data.content) {
                        textEl.textContent = data.content;
                    }
                    var tag = el.querySelector('.message-edited-tag');
                    if (!tag) {
                        tag = document.createElement('span');
                        tag.className = 'message-edited-tag';
                        tag.textContent = '(edited)';
                        el.querySelector('.message-text')?.appendChild(tag);
                    }
                }
            },
            onMessageDeleted: (data) => {
                const el = document.querySelector(`.message[data-msg-id="${data.message_id}"]`);
                if (el) {
                    if (data.delete_for_all) {
                        el.remove();
                    } else {
                        const textEl = el.querySelector('.message-text');
                        if (textEl) textEl.textContent = '[Message deleted]';
                        el.classList.add('deleted');
                    }
                }
            },
            onReactionUpdated: (data) => {
                const el = document.querySelector(`.message[data-msg-id="${data.message_id}"]`);
                if (el) updateReactionBadges(el, data.reactions || []);
            },
            onChannelMessage: (data) => {
                if (activeChannelId === data.channel_id) {
                    appendChannelMessage(data);
                }
            },
            onGroupMessage: (data) => {
                if (activeGroupId === data.group_chat_id) {
                    appendGroupMessage(data);
                }
            },
            onGroupKeyShared: async (data) => {
                if (activeGroupId === data.group_id && data.owner_id !== currentUser.id) {
                    await loadGroupSharedKey(data.group_id, data.owner_id);
                    await renderGroupMessages(data.group_id);
                }
                if (activeGroupId === data.group_id && data.target_id === currentUser.id) {
                    await renderGroupMessages(data.group_id);
                }
            },
            onGroupKeyRevoked: async (data) => {
                delete broadcastKeyCache['g:' + data.owner_id];
                if (activeGroupId === data.group_id && data.target_id === currentUser.id) {
                    await renderGroupMessages(data.group_id);
                }
            },
            onGroupMemberJoined: async (data) => {
                if (activeGroupId === data.group_id) {
                    addSystemMessage(data.username + ' joined the group');
                    if (data.public_key && data.user_id !== currentUser.id) {
                        await _shareMyGroupKeyDirect(data.group_id, data.user_id, data.public_key);
                        await loadGroupSharedKey(data.group_id, data.user_id);
                        await renderGroupMessages(data.group_id);
                    }
                }
            },
            onGroupMemberLeft: async (data) => {
                if (activeGroupId === data.group_id) {
                    addSystemMessage(data.username + ' left the group');
                }
            },
            onGroupMemberRemoved: async (data) => {
                if (activeGroupId === data.group_id) {
                    loadUsers();
                }
            },
        });
    }

    // ── permission requests ──
    async function loadIncomingRequests() {
        const token = localStorage.getItem("token");
        try {
            const [incRes, outRes] = await Promise.all([
                apiFetch("/api/permissions/incoming", { headers: { Authorization: `Bearer ${token}` } }),
                apiFetch("/api/permissions/outgoing", { headers: { Authorization: `Bearer ${token}` } }),
            ]);
            const incoming = await incRes.json();
            const outgoing = await outRes.json();
            renderIncomingRequests(incoming, outgoing);
        } catch (e) {
            console.error("loadIncomingRequests failed:", e);
        }
    }

    function renderIncomingRequests(requests, outgoing) {
        const container = $("requests-list");
        const outgoingContainer = $("outgoing-list");
        const countEl = $("invite-count");
        const empty = $("invites-empty");
        const total = requests.length + (outgoing ? outgoing.length : 0);

        if (total === 0) {
            countEl.classList.add("hidden");
            if (empty) empty.classList.remove("hidden");
            if (container) container.innerHTML = "";
            if (outgoingContainer) outgoingContainer.innerHTML = "";
            return;
        }
        countEl.textContent = total;
        countEl.classList.remove("hidden");
        if (empty) empty.classList.add("hidden");

        // Incoming
        if (container) {
            container.innerHTML = "";
            requests.forEach((r) => {
                const div = document.createElement("div");
                div.className = "request-item";
                div.innerHTML = `
                    <span class="request-user">${escHtml(r.requester_username)} wants to connect</span>
                    <div class="request-actions">
                        <button class="btn-approve" data-id="${r.id}">✓</button>
                        <button class="btn-reject" data-id="${r.id}">✗</button>
                    </div>
                `;
                div.querySelector(".btn-approve").onclick = () => respondToRequest(r.id, "approve");
                div.querySelector(".btn-reject").onclick = () => respondToRequest(r.id, "reject");
                container.appendChild(div);
            });
        }

        // Outgoing
        if (outgoingContainer && outgoing) {
            outgoingContainer.innerHTML = "";
            outgoing.forEach((r) => {
                const div = document.createElement("div");
                div.className = "request-item";
                div.innerHTML = `
                    <span class="request-user">Request sent to ${escHtml(r.owner_username)}</span>
                    <button class="btn-cancel-outgoing" onclick="cancelOutgoingRequest(${r.owner_id})">Cancel</button>
                `;
                outgoingContainer.appendChild(div);
            });
        }
    }

    window.cancelOutgoingRequest = async function(userId) {
        const token = localStorage.getItem("token");
        try {
            await apiFetch(`/api/permissions/outgoing/${userId}`, {
                method: "DELETE",
                headers: { Authorization: `Bearer ${token}` },
            });
            await loadIncomingRequests();
            await loadUsers();
        } catch (e) {
            console.error("cancelOutgoingRequest failed:", e);
        }
    };

    async function respondToRequest(permId, action) {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch(`/api/permissions/${permId}/${action}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                console.error("respond failed:", await parseError(res));
                return;
            }
            const perm = await res.json();
            MESSENGER_SOCKET.notifyPermissionResponded(perm.requester_id, action);
            await loadIncomingRequests();
            await loadUsers();
        } catch (e) {
            console.error("respondToRequest failed:", e);
        }
    }

    // ── unread counts ──
    async function fetchUnreadCounts() {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch("/api/messages/unread-counts", {
                headers: { Authorization: `Bearer ${token}` },
            });
            const data = await res.json();
            unreadCounts = {};
            for (const [userId, count] of Object.entries(data)) {
                if (count > 0) unreadCounts[parseInt(userId)] = count;
            }
            updateTitle();
            // update badges in user list
            document.querySelectorAll(".user-item").forEach((item) => {
                const uid = parseInt(item.dataset.userId);
                const count = unreadCounts[uid] || 0;
                const avatar = item.querySelector(".user-avatar");
                if (avatar) {
                    let badge = item.querySelector(".unread-badge");
                    if (count > 0) {
                        if (!badge) {
                            badge = document.createElement("span");
                            badge.className = "unread-badge";
                            avatar.appendChild(badge);
                        }
                        badge.textContent = count;
                    } else if (badge) {
                        badge.remove();
                    }
                }
            });
        } catch (e) {
            console.error("fetchUnreadCounts failed:", e);
        }
    }

    // ── load / filter users ──
    async function loadUsers() {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch("/api/users", {
                headers: { Authorization: `Bearer ${token}` },
            });
            renderUserList(await res.json());
        } catch (e) {
            console.error("loadUsers failed:", e);
        }
    }

    let searchTimer = null;

    window.handleSearch = function () {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(async () => {
            const q = $("search-input").value.trim();
            const token = localStorage.getItem("token");
            try {
                const url = q ? `/api/users/search?q=${encodeURIComponent(q)}` : "/api/users";
                const res = await apiFetch(url, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const users = await res.json();
                renderUserList(users);
            } catch (e) {
                console.error("search failed:", e);
            }
        }, 250);
    };

    function renderUserList(users) {
        const list = $("user-list");
        const empty = $("search-empty");
        list.innerHTML = "";

        if (!users.length) {
            empty.classList.remove("hidden");
            return;
        }
        empty.classList.add("hidden");

        users.forEach((u) => {
            userCache[u.id] = u;
            const div = document.createElement("div");
            div.className = "user-item" + (activeChatId === u.id ? " active" : "");
            div.dataset.userId = u.id;

            const letter = avatarLetter(u.username);
            const unread = unreadCounts[u.id] || 0;

            let statusText, statusClass;
            let actionBtn = "";
            if (u.is_online) {
                statusText = '🟢 Online';
                statusClass = 'status-online';
            } else if (u.last_seen) {
                const d = new Date(u.last_seen);
                statusText = `Last seen: ${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
                statusClass = 'status-offline';
            } else if (u.permission_status === "approved") {
                statusText = "✓ Can chat";
                statusClass = "status-approved";
            } else if (u.permission_status === "pending") {
                const isOwner = currentUser && u.id > 0;
                statusText = "⏳ Pending";
                statusClass = "status-pending";
            } else if (u.permission_status === "rejected") {
                statusText = "✗ Rejected";
                statusClass = "status-rejected";
            } else {
                statusText = "Request";
                statusClass = "status-none";
                actionBtn = `<button class="btn-request" data-id="${u.id}" data-name="${escHtml(u.username)}">+</button>`;
            }

            const badge = unread ? `<span class="unread-badge">${unread}</span>` : "";

            div.innerHTML = `
                <div class="user-avatar">${letter}${badge}${u.is_online ? '<span class="online-dot"></span>' : ''}</div>
                <div class="user-item-info">
                    <div class="user-name">${escHtml(u.username)}</div>
                    <div class="user-last-msg ${statusClass}">${statusText}</div>
                </div>
                ${actionBtn}
            `;

            const reqBtn = div.querySelector(".btn-request");
            if (reqBtn) {
                reqBtn.onclick = (e) => {
                    e.stopPropagation();
                    requestPermission(u.id, u.username);
                };
            }

            if (u.permission_status === "approved") {
                div.onclick = () => openChat(u, div);
            } else if (u.permission_status === "pending" || u.permission_status === "none" || u.permission_status === "rejected") {
                div.style.cursor = "default";
                div.onclick = null;
            }

            list.appendChild(div);
        });
    }

    async function requestPermission(userId, username) {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch(`/api/permissions/request/${userId}`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (!res.ok) {
                alert(await parseError(res));
                return;
            }
            MESSENGER_SOCKET.notifyPermissionRequested(userId);
            await loadUsers();
        } catch (e) {
            console.error("requestPermission failed:", e);
        }
    }

    // ── share my key with a user ──
    async function shareMyKey(userId) {
        const target = userCache[userId] || null;
        if (!target || !target.public_key) {
            console.warn("[shareMyKey] missing target or public_key for", userId);
            return false;
        }
        if (!currentUser || !currentUser.broadcast_key) {
            console.warn("[shareMyKey] missing currentUser or broadcast_key");
            return false;
        }
        try {
            const encrypted = await CRYPTO.encryptBroadcastKey(
                b64dec(currentUser.broadcast_key),
                b64dec(target.public_key)
            );
            MESSENGER_SOCKET.shareKey(userId, encrypted);
            broadcastKeyCache[userId] = broadcastKeyCache[userId] || null;
            console.log("[shareMyKey] shared key with user", userId);
            return true;
        } catch (e) {
            console.error("[shareMyKey] encryption failed:", e);
            return false;
        }
    }

    // ── toggle key sharing for a chat partner ──
    async function toggleKeySharing(userId) {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch(`/api/messages/${userId}/has-my-key`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const isShared = await res.json();

            if (isShared) {
                if (!confirm("Revoke access to your messages from this user?")) return;
                // revoke
                const delRes = await apiFetch(`/api/messages/${userId}/shared-key`, {
                    method: "DELETE",
                    headers: { Authorization: `Bearer ${token}` },
                });
                if (delRes.ok || delRes.status === 204) {
                    delete broadcastKeyCache[userId];
                    $("chat-revoke-btn").textContent = "🔒";
                    $("chat-revoke-btn").title = "Share your key";
                    if (activeChatId === userId) await renderMessages(userId);
                }
            } else {
                // share — onKeyShared callback will load the key
                const ok = await shareMyKey(userId);
                if (ok) {
                    $("chat-revoke-btn").textContent = "🔑";
                    $("chat-revoke-btn").title = "Revoke your key";
                }
            }
        } catch (e) {
            console.error("toggleKeySharing failed:", e);
        }
    }

    // ── request key access from a chat partner ──
    async function requestKeyAccess(userId) {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch(`/api/messages/${userId}/request-key`, {
                method: "POST",
                headers: { Authorization: `Bearer ${token}` },
            });
            if (res.status === 429) {
                const err = await res.json();
                alert(err.detail || "Too many requests");
                return;
            }
            if (!res.ok) {
                const msg = await parseError(res);
                console.error("requestKeyAccess failed:", msg);
                return;
            }
            if (activeChatId) {
                await renderMessages(activeChatId);
            }
        } catch (e) {
            console.error("requestKeyAccess failed:", e);
        }
    }

    // ── open chat ──
    async function openChat(user, el) {
        activeChatId = user.id;
        activeGroupId = null;
        activeChannelId = null;

        document.querySelectorAll(".user-item").forEach((e) => e.classList.remove("active"));
        if (el) el.classList.add("active");
        activeChatEl = el;

        // clear unread for this user
        delete unreadCounts[user.id];
        updateTitle();
        if (el) {
            const badge = el.querySelector(".unread-badge");
            if (badge) badge.remove();
        }

        const letter = avatarLetter(user.username);
        $("chat-avatar").textContent = letter;
        $("chat-name").textContent = user.username;

        // show toggle only for approved contacts
        if (user.permission_status === "approved") {
            $("chat-revoke-btn").classList.remove("hidden");
            $("chat-key-status").classList.remove("hidden");
            $("chat-request-key-btn").classList.remove("hidden");
            const token = localStorage.getItem("token");

            // my key shared with them?
            const hasMyKeyRes = await apiFetch(`/api/messages/${user.id}/has-my-key`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const isMyKeyShared = await hasMyKeyRes.json();
            $("chat-revoke-btn").textContent = isMyKeyShared ? "🔑" : "🔒";
            $("chat-revoke-btn").title = isMyKeyShared ? "Revoke your key" : "Share your key";
            $("chat-revoke-btn").onclick = () => toggleKeySharing(user.id);
            $("chat-key-status").textContent = isMyKeyShared
                ? "✓ Key shared with contact"
                : "✗ Key not shared";

            // their key shared with me?
            const theirKeyRes = await apiFetch(`/api/messages/${user.id}/shared-key`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const theirKey = await theirKeyRes.json();
            const hasTheirKey = !!(theirKey && theirKey.encrypted_broadcast_key);
            if (hasTheirKey) {
                $("chat-request-key-btn").classList.add("hidden");
            } else {
                $("chat-request-key-btn").classList.remove("hidden");
                $("chat-request-key-btn").onclick = () => requestKeyAccess(user.id);
            }
        } else {
            $("chat-revoke-btn").classList.add("hidden");
            $("chat-key-status").classList.add("hidden");
            $("chat-request-key-btn").classList.add("hidden");
        }

        $("chat-header").classList.remove("hidden");
        $("chat-area").classList.remove("hidden");
        $("no-chat").classList.add("hidden");
        $("message-input").disabled = false;
        $("send-btn").disabled = false;
        $("message-input").focus();

        if (window.innerWidth <= 860) {
            document.querySelector('.sidebar').classList.remove('open');
            document.getElementById('sidebar-backdrop').classList.remove('visible');
        }

        MESSENGER_SOCKET.joinRoom(user.id);
        await loadSharedKey(user.id);
        await renderMessages(user.id);
        // mark messages as read
        const token = localStorage.getItem("token");
        await apiFetch(`/api/messages/${user.id}/read`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}` },
        });
        delete unreadCounts[user.id];
        updateTitle();
        fetchUnreadCounts();
    }

    async function loadSharedKey(userId) {
        const token = localStorage.getItem("token");
        const res = await apiFetch(`/api/messages/${userId}/shared-key`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 200) {
            const data = await res.json();
            if (data && data.encrypted_broadcast_key) {
                if (!privateKey) {
                    console.warn("[loadSharedKey] privateKey is null — cannot decrypt shared broadcast key. Try re-login.");
                    delete broadcastKeyCache[userId];
                    return;
                }
                try {
                    const raw = await CRYPTO.decryptBroadcastKey(b64dec(data.encrypted_broadcast_key), privateKey);
                    broadcastKeyCache[userId] = await CRYPTO.importBroadcastKey(raw);
                    console.log("[loadSharedKey] loaded broadcast key for user", userId);
                    return;
                } catch (e) {
                    console.error("[loadSharedKey] decrypt shared key failed:", e);
                }
            } else {
                console.log("[loadSharedKey] no shared key from user", userId);
            }
        } else {
            console.log("[loadSharedKey] API returned", res.status, "for user", userId);
        }
        delete broadcastKeyCache[userId];
    }

    // ── messages ──
    async function renderMessages(peerId) {
        const token = localStorage.getItem("token");
        const res = await apiFetch(`/api/messages/${peerId}`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const messages = await res.json();
        const container = $("messages");
        container.innerHTML = "";

        for (const msg of messages) {
            const isMine = msg.sender_id === currentUser.id;
            const div = document.createElement("div");

            if (msg.type === "system") {
                div.className = "message system";
                div.textContent = msg.encrypted_content;
                container.appendChild(div);
                continue;
            }

            div.className = "message " + (isMine ? "mine" : "theirs");
            div.dataset.msgId = msg.id;
            div.addEventListener("contextmenu", function(e) {
                e.preventDefault();
                showContextMenu(e, { id: msg.id, sender_id: msg.sender_id, text: msg.encrypted_content || msg.content || "" });
            });

            const text = document.createElement("div");
            text.className = "message-text";

            let displayText;
            if (isMine && myBroadcastKey) {
                displayText = await CRYPTO.decryptMessage(msg.encrypted_content, myBroadcastKey);
            } else if (broadcastKeyCache[peerId]) {
                displayText = await CRYPTO.decryptMessage(msg.encrypted_content, broadcastKeyCache[peerId]);
            }
            if (displayText === null || displayText === undefined) displayText = "[Encrypted message]";

            var hasAttachments = msg.attachments && msg.attachments.length > 0;

            if (displayText.startsWith('> ')) {
                var sepIdx = displayText.indexOf('\n\n');
                if (sepIdx > 0) {
                    var quoteRaw = displayText.substring(0, sepIdx);
                    var replyBody = displayText.substring(sepIdx + 2);
                    var quoteClean = quoteRaw.split('\n').map(function (line) {
                        return line.startsWith('> ') ? line.substring(2) : line;
                    }).join('\n');
                    var quoteEl = document.createElement('div');
                    quoteEl.className = 'message-quote';
                    quoteEl.textContent = quoteClean;
                    div.appendChild(quoteEl);
                    text.textContent = replyBody;
                } else {
                    text.textContent = displayText;
                }
            } else if (displayText || !hasAttachments) {
                text.textContent = displayText;
            }
            if (text.textContent) {
                div.appendChild(text);
            }

            if (msg.attachments && msg.attachments.length > 0) {
                var attDiv = document.createElement('div');
                attDiv.className = 'message-attachments';
                var imageKey = isMine ? myBroadcastKey : broadcastKeyCache[peerId];
                msg.attachments.forEach(function (att) {
                    var imgWrap = document.createElement('div');
                    imgWrap.className = 'message-image';
                    var placeholder = document.createElement('span');
                    placeholder.className = 'img-loading';
                    placeholder.textContent = '…';
                    imgWrap.appendChild(placeholder);
                    imgWrap.onclick = function () {
                        var img = imgWrap.querySelector('img');
                        if (img) openImageViewer(img.src);
                    };
                    attDiv.appendChild(imgWrap);
                    fetchAndDecryptImage(att.id, imageKey).then(function (src) {
                        if (src) {
                            placeholder.remove();
                            var imgEl = document.createElement('img');
                            imgEl.src = src;
                            imgEl.alt = '';
                            imgWrap.appendChild(imgEl);
                        } else {
                            placeholder.textContent = '🔒';
                        }
                    });
                });
                div.appendChild(attDiv);
            }

            div.addEventListener('contextmenu', function (ev) {
                ev.preventDefault();
                var msgText = displayText;
                if (msgText.startsWith('> ') && msgText.indexOf('\n\n') > 0) {
                    msgText = msgText.substring(msgText.indexOf('\n\n') + 2);
                }
                showContextMenu(ev, {
                    messageId: msg.id,
                    senderId: msg.sender_id,
                    senderName: msg.sender_id === currentUser.id ? currentUser.username : (userCache[peerId] ? userCache[peerId].username : ''),
                    text: msgText
                });
            });

            const time = document.createElement("div");
            time.className = "message-time";
            const readMark = isMine ? (msg.is_read ? " ✓✓" : " ✓") : "";
            time.textContent = new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + readMark;

            container.appendChild(div);
        }
        container.scrollTop = container.scrollHeight;
    }

    async function handleIncomingMessage(data) {
        console.log("[socket] new_message received, type:", data.type, "sender:", data.sender_id, "receiver:", data.receiver_id);
        if (data.type === "system") {
            const peerId = data.sender_id === currentUser.id ? data.receiver_id : data.sender_id;
            if (activeChatId === peerId) {
                await renderMessages(peerId);
            }
            return;
        }
        const ownMessage = data.sender_id === currentUser.id;
        const peerId = ownMessage ? data.receiver_id : data.sender_id;
        console.log("[socket] peerId:", peerId, "activeChatId:", activeChatId, "hasFocus:", document.hasFocus(), "own:", ownMessage);
        if (ownMessage && activeChatId === peerId) {
            return; // ack callback in sendMessage handles renderMessages
        }
        if (activeChatId === peerId) {
            if (!broadcastKeyCache[peerId]) {
                await loadSharedKey(peerId);
            }
            await renderMessages(peerId);
            const now = Date.now();
            if (!readThrottle[peerId] || now - readThrottle[peerId] > 1000) {
                readThrottle[peerId] = now;
                const token = localStorage.getItem("token");
                await apiFetch(`/api/messages/${peerId}/read`, {
                    method: "POST",
                    headers: { Authorization: `Bearer ${token}` },
                });
            }
            if (!document.hasFocus()) {
                showObfuscatedNotification(data.sender_username);
            }
        } else {
            unreadCounts[peerId] = (unreadCounts[peerId] || 0) + 1;
            const senderName = data.sender_username || userCache[peerId]?.username || "";
            updateTitle(senderName);
            fetchUnreadCounts();
            showObfuscatedNotification(senderName);
        }
    }

    // ── send message ──
    window.sendMessage = async function () {
        console.log("[sendMessage] === START === activeChatId:", activeChatId, "myBroadcastKey:", !!myBroadcastKey, "currentUser:", currentUser ? currentUser.id : null);
        try {
            const input = $("message-input");
            const text = input.value.trim();
            const token = localStorage.getItem("token");
            console.log("[sendMessage] input:", JSON.stringify(text).substring(0, 50), "tokenLen:", token ? token.length : 0, "pendingImages:", pendingImages.length);
            if ((!text && pendingImages.length === 0) || (!activeChatId && !activeGroupId && !activeChannelId)) {
                console.warn("[sendMessage] skipped: no text/images or no active chat/group/channel");
                return;
            }
            input.value = "";

            let finalText = text;
            if (replyTo) {
                const quoteLines = replyTo.text.split('\n').map(function (line) { return '> ' + line; }).join('\n');
                finalText = quoteLines + '\n\n' + text;
                cancelReply();
            }

            var attachmentIds = [];
            if (pendingImages.length > 0) {
                try {
                    attachmentIds = await uploadImages();
                } catch (e) {
                    console.error('[sendMessage] image upload failed:', e);
                    return;
                }
            }

            if (!finalText && attachmentIds.length === 0) return;

            if (!activeChatId && !activeGroupId && !activeChannelId) {
                console.warn("[sendMessage] no active conversation");
                return;
            }

            if (!myBroadcastKey) {
                console.error("[sendMessage] myBroadcastKey is null — cannot encrypt. Try re-login.");
                alert("Cannot send message: encryption key is missing. Please re-login.");
                return;
            }

            const encrypted = await CRYPTO.encryptMessage(finalText, myBroadcastKey);

            if (activeGroupId) {
                try {
                    var gRes = await apiFetch(`/api/groups/${activeGroupId}/messages`, {
                        method: "POST",
                        headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json" },
                        body: JSON.stringify({ encrypted_content: encrypted, attachment_ids: attachmentIds }),
                    });
                    if (gRes.ok) {
                        await renderGroupMessages(activeGroupId);
                    } else {
                        console.error("group post failed:", gRes.status, await gRes.text());
                    }
                } catch (e) { console.error("send group msg failed:", e); }
                return;
            }

            if (activeChannelId) {
                try {
                    var cRes = await apiFetch(`/api/channels/${activeChannelId}/post`, {
                        method: "POST",
                        headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json" },
                        body: JSON.stringify({ encrypted_content: finalText, attachment_ids: attachmentIds }),
                    });
                    if (cRes.ok) {
                        await loadChannelMessages(activeChannelId);
                    } else {
                        console.error("channel post failed:", cRes.status, await cRes.text());
                    }
                } catch (e) { console.error("send channel msg failed:", e); }
                return;
            }

            // ══ DM path ══

            console.log("[sendMessage] checking has-my-key for", activeChatId);
            const hasMyKeyRes = await apiFetch(`/api/messages/${activeChatId}/has-my-key`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const hasMyKey = await hasMyKeyRes.json();
            if (!hasMyKey) {
                const shared = await shareMyKey(activeChatId);
                if (!shared) {
                    alert("Cannot send message: unable to share your encryption key.");
                    return;
                }
            }
            console.log("[sendMessage] encrypt OK, calling socket.sendMessage...");
            MESSENGER_SOCKET.sendMessage(activeChatId, encrypted, attachmentIds, async function (ack) {
                if (ack && ack.error) {
                    console.error("[sendMessage] socket rejected:", ack.error, ack.detail);
                    if (ack.error === "not_connected" || ack.error === "not_initialized") {
                        console.log("[sendMessage] falling back to REST API...");
                        try {
                            var restRes = await apiFetch(`/api/messages/${activeChatId}/send`, {
                                method: "POST",
                                headers: {
                                    "Authorization": "Bearer " + (appToken || localStorage.getItem("token")),
                                    "Content-Type": "application/json",
                                },
                                body: JSON.stringify({ encrypted_content: encrypted, attachment_ids: attachmentIds }),
                            });
                            if (restRes.ok) {
                                var sendResult = await restRes.json();
                                console.log("[sendMessage] === DONE === REST fallback OK, id:", sendResult.message_id);
                                await renderMessages(activeChatId);
                            } else {
                                var errText = await restRes.text();
                                console.error("[sendMessage] REST fallback failed:", restRes.status, errText);
                                alert("Message failed to send: " + errText);
                            }
                        } catch (restErr) {
                            console.error("[sendMessage] REST fallback error:", restErr.message || restErr);
                            alert("Message send failed. See console for details.");
                        }
                    } else {
                        alert("Message not delivered: " + ack.error);
                    }
                } else {
                    console.log("[sendMessage] === DONE === server ack OK");
                    await renderMessages(activeChatId);
                }
            });
        } catch (e) {
            console.error("[sendMessage] CATCH:", e.message || e, e);
            alert("Failed to send message. See console for details.");
        }
    };

    // ── typing ──
    window.handleTyping = function () {
        if (!activeChatId) return;
        MESSENGER_SOCKET.sendTyping(activeChatId, true);
        clearTimeout(typingTimer);
        typingTimer = setTimeout(() => MESSENGER_SOCKET.sendTyping(activeChatId, false), 1000);
    };

    function handleTypingIndicator(data) {
        const el = $("typing-indicator");
        el.textContent = data.is_typing ? "typing..." : "";
        el.classList.toggle("hidden", !data.is_typing);
    }

    window.cancelReply = function () {
        replyTo = null;
        $("reply-bar").classList.add("hidden");
    };

    function startReply(msgData) {
        replyTo = msgData;
        $("reply-name").textContent = msgData.senderName;
        $("reply-text").textContent = msgData.text.length > 80 ? msgData.text.substring(0, 80) + '...' : msgData.text;
        $("reply-bar").classList.remove("hidden");
        $("message-input").focus();
    }

    function showContextMenu(e, msgData) {
        hideContextMenu();
        contextMenuTarget = msgData;
        const menu = $("context-menu");
        menu.style.left = e.pageX + 'px';
        menu.style.top = e.pageY + 'px';
        menu.classList.remove("hidden");
    }

    function hideContextMenu() {
        contextMenuTarget = null;
        $("context-menu").classList.add("hidden");
    }

    window.startContextReply = function () {
        if (contextMenuTarget) {
            startReply(contextMenuTarget);
        }
        hideContextMenu();
    };

    document.addEventListener('click', function (e) {
        if (!e.target.closest('#context-menu')) {
            hideContextMenu();
        }
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            if (replyTo) {
                cancelReply();
            } else {
                hideContextMenu();
            }
        }
    });

    document.addEventListener('paste', function (e) {
        if (!activeChatId) return;
        var items = e.clipboardData && e.clipboardData.items;
        if (!items) return;
        var imageFiles = [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].type.match(/image\//)) {
                var f = items[i].getAsFile();
                if (f) imageFiles.push(f);
            }
        }
        if (imageFiles.length > 0) {
            e.preventDefault();
            addImages(imageFiles);
        }
    });

    // ── autorun ──
    const savedToken = localStorage.getItem("token");
    console.log("[autorun] savedToken present:", !!savedToken);
    if (savedToken) {
        initApp(savedToken).then(function() {
            handleJoinLink();
        }).catch((e) => {
            console.error("[autorun] initApp failed:", e.message || e, e);
            localStorage.clear();
            sessionStorage.clear();
            showPage("login-page");
        });
    }

    async function handleJoinLink() {
        var path = window.location.pathname;
        var match = path.match(/^\/join\/([a-zA-Z0-9_\-]+)/);
        if (!match) return;
        var code = match[1];
        console.log("[join] invite code:", code);
        try {
            var infoRes = await apiFetch("/api/groups/info/" + code);
            if (!infoRes.ok) {
                alert("Invalid invite link: group not found");
                window.history.replaceState(null, "", "/");
                return;
            }
            var info = await infoRes.json();
            if (confirm("Join group \"" + info.name + "\"?")) {
                var res = await apiFetch("/api/groups/join/" + code, {
                    method: "POST",
                    headers: { "Authorization": "Bearer " + (appToken || savedToken) },
                });
                if (res.ok) {
                    window.history.replaceState(null, "", "/");
                    var group = await res.json();
                    await loadUsers();
                    if (confirm("Joined " + group.name + "! Open it now?")) {
                        openGroupChat(group);
                    }
                } else {
                    var err = await res.json();
                    alert("Join failed: " + (err.detail || "Unknown error"));
                    window.history.replaceState(null, "", "/");
                }
            } else {
                window.history.replaceState(null, "", "/");
            }
        } catch (e) {
            console.error("[join] failed:", e);
        }
    }

    // ═══════════════════════════════════════════════════════
    //  NEW FEATURES: Block, Channels, Groups, Edit/Delete/React
    // ═══════════════════════════════════════════════════════

    // ── Block ──
    async function loadBlocked() {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch("/api/users/blocked", { headers: { Authorization: `Bearer ${token}` } });
            const blocked = await res.json();
            renderBlocked(blocked);
        } catch (e) { console.error("loadBlocked failed:", e); }
    }

    function renderBlocked(blocked) {
        const container = $("blocked-list");
        const empty = $("blocked-empty");
        const tabBtn = $("tab-blocked");
        if (!blocked.length) {
            tabBtn.classList.add("hidden");
            if (empty) empty.classList.remove("hidden");
            if (container) container.innerHTML = "";
            return;
        }
        tabBtn.classList.remove("hidden");
        if (empty) empty.classList.add("hidden");
        if (container) {
            container.innerHTML = "";
            blocked.forEach((u) => {
                const div = document.createElement("div");
                div.className = "request-item";
                div.innerHTML = `
                    <span class="request-user">${escHtml(u.username)}</span>
                    <button class="btn-unblock" onclick="unblockUser(${u.id})">Unblock</button>
                `;
                container.appendChild(div);
            });
        }
    }

    window.blockUser = async function(userId) {
        if (!confirm("Block this user? All permissions and keys will be revoked.")) return;
        const token = localStorage.getItem("token");
        await apiFetch(`/api/users/${userId}/block`, { method: "POST", headers: { Authorization: `Bearer ${token}` } });
        await loadUsers();
    };

    window.unblockUser = async function(userId) {
        const token = localStorage.getItem("token");
        await apiFetch(`/api/users/${userId}/block`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
        await loadBlocked();
        await loadUsers();
    };

    // ── Context menu ──
    document.addEventListener("click", function(e) {
        if (!e.target.closest("#context-menu") && !e.target.closest(".message")) {
            $("context-menu").classList.add("hidden");
        }
    });

    function showContextMenu(e, msgData) {
        contextMenuTarget = msgData;
        const menu = $("context-menu");
        var x = e.clientX;
        var y = e.clientY;
        var w = menu.offsetWidth || 170;
        var h = menu.offsetHeight || 220;
        if (x + w > window.innerWidth) x = window.innerWidth - w - 10;
        if (y + h > window.innerHeight) y = window.innerHeight - h - 10;
        if (x < 10) x = 10;
        if (y < 10) y = 10;
        menu.style.left = x + "px";
        menu.style.top = y + "px";
        menu.classList.remove("hidden");

        const isOwner = msgData.sender_id === currentUser.id;
        var ownerItems = menu.querySelectorAll(".cm-owner-only");
        ownerItems.forEach(function(it) {
            it.classList.toggle("hidden", !isOwner);
        });
    }

    window.editContextMessage = async function() {
        if (!contextMenuTarget) return;
        $("context-menu").classList.add("hidden");
        const newText = prompt("Edit message:", contextMenuTarget.text);
        if (newText === null || newText === contextMenuTarget.text) return;
        const token = localStorage.getItem("token");
        var encContent = "";
        if (myBroadcastKey) {
            encContent = await CRYPTO.encryptMessage(newText, myBroadcastKey);
        }
        await apiFetch(`/api/messages/${contextMenuTarget.id}`, {
            method: "PUT",
            headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
            body: JSON.stringify({ encrypted_content: encContent }),
        });
    };

    window.deleteContextMessage = async function(deleteForAll) {
        if (!contextMenuTarget) return;
        $("context-menu").classList.add("hidden");
        if (!confirm(deleteForAll ? "Delete for all?" : "Delete for you?")) return;
        const token = localStorage.getItem("token");
        const url = `/api/messages/${contextMenuTarget.id}` + (deleteForAll ? "?delete_for_all=true" : "");
        await apiFetch(url, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
    };

    window.reactContextMessage = async function(emoji) {
        $("context-menu").classList.add("hidden");
        if (!contextMenuTarget || !contextMenuTarget.id) {
            console.warn("[react] no contextMenuTarget.id");
            return;
        }
        var msgId = contextMenuTarget.id;
        var token = localStorage.getItem("token");
        await apiFetch(`/api/messages/${msgId}/reactions`, {
            method: "POST",
            headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
            body: JSON.stringify({ emoji: emoji }),
        });
    };

    function updateReactionBadges(el, reactions) {
        var existing = el.querySelector(".message-reactions");
        if (existing) existing.remove();
        if (!reactions.length) return;

        const container = document.createElement("div");
        container.className = "message-reactions";
        reactions.forEach(function(r) {
            const badge = document.createElement("span");
            badge.className = "message-reaction-badge";
            badge.textContent = r.emoji + " " + (r.count || 1);
            badge.onclick = function() {
                reactContextMessageFromEl(el, r.emoji);
            };
            container.appendChild(badge);
        });
        el.appendChild(container);
    }

    function reactContextMessageFromEl(el, emoji) {
        const msgId = parseInt(el.dataset.msgId);
        if (!msgId) return;
        contextMenuTarget = { id: msgId };
        reactContextMessage(emoji);
    }

    // ── Channels ──
    async function loadChannels() {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch("/api/channels", { headers: { Authorization: `Bearer ${token}` } });
            const channels = await res.json();
            renderChannels(channels);
        } catch (e) { console.error("loadChannels failed:", e); }
    }

    function renderChannels(channels) {
        const container = $("channel-list");
        if (!container) return;
        container.innerHTML = "";
        channels.forEach(function(c) {
            const div = document.createElement("div");
            div.className = "user-item";
            div.dataset.channelId = c.id;
            const subText = c.is_subscribed ? "Subscribed" : "Join";
            const subBtn = c.is_subscribed ? "" : `<button class="btn-request" onclick="event.stopPropagation(); subscribeChannel(${c.id})">+</button>`;
            div.innerHTML = `
                <div class="user-avatar">${c.is_system ? '📢' : '#'}</div>
                <div class="user-item-info">
                    <div class="user-name">${escHtml(c.name)}</div>
                    <div class="user-last-msg">${c.subscriber_count} subscribers · ${subText}</div>
                </div>
                ${subBtn}
            `;
            if (c.is_subscribed) {
                div.onclick = function() { openChannel(c, div); };
            }
            container.appendChild(div);
        });
    }

    window.showCreateChannelDialog = function() {
        $("create-channel-dialog").classList.remove("hidden");
    };

    window.hideCreateChannelDialog = function() {
        $("create-channel-dialog").classList.add("hidden");
    };

    window.createChannel = async function() {
        var name = $("new-channel-name").value.trim();
        var desc = $("new-channel-desc").value.trim();
        if (!name) return;
        const token = localStorage.getItem("token");
        try {
            await apiFetch("/api/channels", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ name: name, description: desc }),
            });
            hideCreateChannelDialog();
            $("new-channel-name").value = "";
            $("new-channel-desc").value = "";
            loadChannels();
            switchTab("channels");
        } catch (e) {
            console.error("createChannel failed:", e);
        }
    };

    window.subscribeChannel = async function(channelId) {
        const token = localStorage.getItem("token");
        await apiFetch(`/api/channels/${channelId}/subscribe`, {
            method: "POST", headers: { Authorization: `Bearer ${token}` },
        });
        loadChannels();
    };

    window.handleChannelSearch = function() {
        var q = $("channel-search-input").value.toLowerCase();
        var items = document.querySelectorAll("#channel-list .user-item");
        items.forEach(function(item) {
            var name = (item.querySelector(".user-name")?.textContent || "").toLowerCase();
            item.style.display = name.includes(q) ? "" : "none";
        });
    };

    async function openChannel(channel, el) {
        activeChannelId = channel.id;
        activeChatId = null;
        activeGroupId = null;
        el && el.classList.add("active");
        $("chat-avatar").textContent = "#";
        $("chat-name").textContent = channel.name;
        $("chat-revoke-btn").classList.add("hidden");
        $("chat-key-status").classList.add("hidden");
        $("chat-request-key-btn").classList.add("hidden");
        $("chat-header").classList.remove("hidden");
        $("chat-area").classList.remove("hidden");
        $("no-chat").classList.add("hidden");
        MESSENGER_SOCKET.joinChannelRoom(channel.id);
        loadChannelMessages(channel.id);
    }

    async function loadChannelMessages(channelId) {
        const token = localStorage.getItem("token");
        const res = await apiFetch(`/api/channels/${channelId}/messages`, { headers: { Authorization: `Bearer ${token}` } });
        const messages = await res.json();
        const container = $("messages");
        container.innerHTML = "";
        messages.forEach(function(m) { appendChannelMessage(m); });
    }

    function appendChannelMessage(data) {
        const container = $("messages");
        const div = document.createElement("div");
        div.className = "message";
        div.dataset.msgId = data.id;
        div.innerHTML = `<div class="message-text">${escHtml(data.content || data.encrypted_content || "")}</div>`;
        // context menu for own messages
        div.addEventListener("contextmenu", function(e) {
            e.preventDefault();
            if (data.sender_id === currentUser.id) {
                showContextMenu(e, { id: data.id, sender_id: data.sender_id, text: data.content || data.encrypted_content });
            }
        });
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    // ── Groups ──
    window.showCreateGroupDialog = function() {
        $("create-group-dialog").classList.remove("hidden");
    };

    window.hideCreateGroupDialog = function() {
        $("create-group-dialog").classList.add("hidden");
    };

    window.createGroup = async function() {
        var name = $("new-group-name").value.trim();
        if (!name) return;
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch("/api/groups", {
                method: "POST",
                headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
                body: JSON.stringify({ name: name }),
            });
            var group = await res.json();
            hideCreateGroupDialog();
            $("new-group-name").value = "";
            if (group.invite_code) {
                var link = `https://${location.host}/join/${group.invite_code}`;
                prompt("Invite link (share with others):", link);
            }
            loadUsers();
            if (confirm("Open group now?")) {
                openGroupChat(group);
            }
        } catch (e) {
            console.error("createGroup failed:", e);
        }
    };

    // ── Join Group ──
    window.showJoinGroupDialog = function() {
        $("join-group-dialog").classList.remove("hidden");
        $("join-invite-code").value = "";
        $("join-group-confirm").classList.add("hidden");
        $("join-lookup-btn").classList.remove("hidden");
        $("join-group-error").classList.add("hidden");
    };

    window.hideJoinGroupDialog = function() {
        $("join-group-dialog").classList.add("hidden");
    };

    var _pendingJoinGroup = null;

    window.lookupGroupInfo = async function() {
        var raw = $("join-invite-code").value.trim();
        if (!raw) return;
        var code = extractInviteCode(raw);
        if (!code) {
            $("join-group-error").textContent = "Invalid invite code";
            $("join-group-error").classList.remove("hidden");
            return;
        }
        $("join-group-error").classList.add("hidden");
        try {
            var res = await apiFetch("/api/groups/info/" + code);
            if (!res.ok) {
                $("join-group-error").textContent = "Group not found";
                $("join-group-error").classList.remove("hidden");
                return;
            }
            var info = await res.json();
            _pendingJoinGroup = { id: info.id, name: info.name, code: code };
            $("join-group-name").textContent = info.name;
            $("join-group-meta").textContent = info.member_count + " members";
            $("join-lookup-btn").classList.add("hidden");
            $("join-group-confirm").classList.remove("hidden");
            $("join-group-error").classList.add("hidden");
        } catch (e) {
            console.error("lookupGroupInfo failed:", e);
        }
    };

    window.confirmJoinGroup = async function() {
        if (!_pendingJoinGroup) return;
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch("/api/groups/join/" + _pendingJoinGroup.code, {
                method: "POST",
                headers: { Authorization: "Bearer " + token },
            });
            if (!res.ok) {
                var err = await res.json();
                $("join-group-error").textContent = err.detail || "Failed to join";
                $("join-group-error").classList.remove("hidden");
                return;
            }
            var group = await res.json();
            hideJoinGroupDialog();
            loadUsers();
            if (confirm("Joined " + group.name + "! Open it now?")) {
                openGroupChat(group);
            }
        } catch (e) {
            console.error("confirmJoinGroup failed:", e);
        }
    };

    function extractInviteCode(raw) {
        var m = raw.match(/(?:join\/)?([a-zA-Z0-9_\-]{12,32})/);
        return m ? m[1] : null;
    }

    async function openGroupChat(group) {
        activeGroupId = group.id;
        activeChatId = null;
        activeChannelId = null;
        $("chat-avatar").textContent = "G";
        $("chat-name").textContent = group.name;
        $("chat-revoke-btn").classList.add("hidden");
        $("chat-key-status").classList.remove("hidden");
        $("chat-key-status").textContent = group.member_count + " members";
        $("chat-request-key-btn").classList.remove("hidden");
        $("chat-request-key-btn").textContent = "Members";
        $("chat-request-key-btn").onclick = function() { showGroupMembersDialog(group.id); };
        $("chat-header").classList.remove("hidden");
        $("chat-area").classList.remove("hidden");
        $("no-chat").classList.add("hidden");
        MESSENGER_SOCKET.joinGroupRoom(group.id);
        await syncGroupKeys(group.id);
        renderGroupMessages(group.id);
    }

    window.showGroupMembersDialog = async function(groupId) {
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch(`/api/groups/${groupId}/members`, { headers: { Authorization: `Bearer ${token}` } });
            var members = await res.json();
            var groupRes = await apiFetch("/api/groups", { headers: { Authorization: `Bearer ${token}` } });
            var groups = await groupRes.json();
            var group = groups.find(function(g) { return g.id === groupId; });

            var isOwner = group && group.owner_id === currentUser.id;

            var list = $("group-members-list");
            list.innerHTML = "";
            members.forEach(function(m) {
                var div = document.createElement("div");
                div.className = "group-member-item";
                var keyBtn = "";
                var kickBtn = "";
                if (m.user_id !== currentUser.id) {
                    keyBtn = `<button class="btn-group-key-toggle" onclick="toggleGroupKey(${groupId}, ${m.user_id})">🔑</button>`;
                    if (isOwner && m.role !== "owner") {
                        kickBtn = `<button class="btn-group-kick" onclick="kickMember(${groupId}, ${m.user_id})">Kick</button>`;
                    }
                }
                div.innerHTML = `
                    <span class="group-member-name">${escHtml(m.username)}</span>
                    <span class="group-member-role">${m.role}</span>
                    ${keyBtn}
                    ${kickBtn}
                `;
                list.appendChild(div);
            });

            // load bans for owner
            var bansSection = $("group-bans-section");
            var bansList = $("group-bans-list");
            bansList.innerHTML = "";
            if (isOwner) {
                bansSection.classList.remove("hidden");
                try {
                    var bansRes = await apiFetch(`/api/groups/${groupId}/bans`, { headers: { Authorization: `Bearer ${token}` } });
                    var bans = await bansRes.json();
                    if (bans.length > 0) {
                        bans.forEach(function(b) {
                            var bDiv = document.createElement("div");
                            bDiv.className = "banned-item";
                            bDiv.innerHTML = `
                                <span class="banned-name">${escHtml(b.username)}</span>
                                <button class="btn-group-unban" onclick="unbanMember(${groupId}, ${b.user_id})">Unban</button>
                            `;
                            bansList.appendChild(bDiv);
                        });
                    } else {
                        bansList.innerHTML = '<span style="color:#5a5a6e;font-size:11px;">No banned users</span>';
                    }
                } catch (e) { console.error("loadBans failed:", e); }
            } else {
                bansSection.classList.add("hidden");
            }

            if (group && group.invite_code) {
                $("group-invite-link").textContent = "Invite: https://" + location.host + "/join/" + group.invite_code;
                $("group-invite-link").classList.remove("hidden");
                if (isOwner) {
                    $("group-regenerate-invite-btn").classList.remove("hidden");
                    _membersDialogGroupId = groupId;
                } else {
                    $("group-regenerate-invite-btn").classList.add("hidden");
                }
            } else {
                $("group-invite-link").classList.add("hidden");
                $("group-regenerate-invite-btn").classList.add("hidden");
            }

            $("group-members-dialog").classList.remove("hidden");
        } catch (e) { console.error("showGroupMembersDialog failed:", e); }
    };

    window.hideGroupMembersDialog = function() {
        $("group-members-dialog").classList.add("hidden");
    };

    var _membersDialogGroupId = null;

    window.regenerateInvite = async function() {
        if (!_membersDialogGroupId) return;
        if (!confirm("Regenerate invite link? The old link will stop working.")) return;
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch(`/api/groups/${_membersDialogGroupId}/regenerate-invite`, {
                method: "POST",
                headers: { Authorization: "Bearer " + token },
            });
            if (res.ok) {
                var group = await res.json();
                if (group.invite_code) {
                    $("group-invite-link").textContent = "Invite: https://" + location.host + "/join/" + group.invite_code;
                    prompt("New invite link:", "https://" + location.host + "/join/" + group.invite_code);
                }
            }
        } catch (e) { console.error("regenerateInvite failed:", e); }
    };

    window.toggleGroupKey = async function(groupId, targetId) {
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch(`/api/groups/${groupId}/members/${targetId}/has-my-key`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            var hasKey = await res.json();
            if (hasKey) {
                await apiFetch(`/api/groups/${groupId}/members/${targetId}/shared-key`, {
                    method: "DELETE", headers: { Authorization: `Bearer ${token}` },
                });
            } else {
                _shareMyGroupKeyWith(groupId, targetId);
            }
        } catch (e) { console.error("toggleGroupKey failed:", e); }
    };

    async function _shareMyGroupKeyWith(groupId, targetId) {
        const token = localStorage.getItem("token");
        if (!currentUser.broadcast_key || !privateKey) return;
        try {
            var memberRes = await apiFetch(`/api/groups/${groupId}/members`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            var members = await memberRes.json();
            var member = members.find(function(m) { return m.user_id === targetId; });
            if (member && member.public_key) {
                var encrypted = await CRYPTO.encryptBroadcastKey(
                    b64dec(currentUser.broadcast_key),
                    b64dec(member.public_key)
                );
                MESSENGER_SOCKET.shareGroupKey(groupId, targetId, encrypted);
            }
        } catch (e) { console.error("_shareMyGroupKeyWith failed:", e); }
    }

    async function _shareMyGroupKeyDirect(groupId, targetId, publicKeyB64) {
        if (!currentUser.broadcast_key || !privateKey || !publicKeyB64) return;
        try {
            var encrypted = await CRYPTO.encryptBroadcastKey(
                b64dec(currentUser.broadcast_key),
                b64dec(publicKeyB64)
            );
            MESSENGER_SOCKET.shareGroupKey(groupId, targetId, encrypted);
        } catch (e) { console.error("_shareMyGroupKeyDirect failed:", e); }
    }

    window.kickMember = async function(groupId, userId) {
        const token = localStorage.getItem("token");
        if (!confirm("Kick and ban this user from the group?")) return;
        try {
            var res = await apiFetch(`/api/groups/${groupId}/ban/${userId}`, {
                method: "POST",
                headers: { Authorization: "Bearer " + token },
            });
            if (res.ok) {
                showGroupMembersDialog(groupId);
                if (activeGroupId === groupId) {
                    loadUsers();
                    renderGroupMessages(groupId);
                }
            }
        } catch (e) { console.error("kickMember failed:", e); }
    };

    window.unbanMember = async function(groupId, userId) {
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch(`/api/groups/${groupId}/ban/${userId}`, {
                method: "DELETE",
                headers: { Authorization: "Bearer " + token },
            });
            if (res.ok) {
                showGroupMembersDialog(groupId);
            }
        } catch (e) { console.error("unbanMember failed:", e); }
    };

    async function renderGroupMessages(groupId) {
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch(`/api/groups/${groupId}/messages`, { headers: { Authorization: `Bearer ${token}` } });
            var messages = await res.json();
            var container = $("messages");
            container.innerHTML = "";
            messages.forEach(function(m) { appendGroupMessage(m); });
        } catch (e) { console.error("renderGroupMessages failed:", e); }
    }

    function appendGroupMessage(data) {
        const container = $("messages");
        var isMine = data.sender_id === currentUser.id;
        var div = document.createElement("div");
        div.className = "message " + (isMine ? "mine" : "theirs");
        div.dataset.msgId = data.id;
        div.innerHTML = `
            <div class="message-sender-name">${escHtml(isMine ? "You" : data.sender_username || "User")}</div>
            <div class="message-text">[Encrypted message]</div>
        `;

        var decryptKey = isMine ? myBroadcastKey : groupKeyCache["g:" + data.sender_id];
        if (decryptKey && data.encrypted_content) {
            _decryptAndShow(div, data.encrypted_content, decryptKey);
        } else if (!isMine && data.encrypted_content && activeGroupId) {
            loadGroupSharedKey(activeGroupId, data.sender_id).then(function() {
                var key = groupKeyCache["g:" + data.sender_id];
                if (key) _decryptAndShow(div, data.encrypted_content, key);
            });
        }
        if (data.content) {
            div.querySelector(".message-text").textContent = data.content;
        }

        div.addEventListener("contextmenu", function(e) {
            e.preventDefault();
            showContextMenu(e, { id: data.id, sender_id: data.sender_id, text: data.encrypted_content || data.content || "" });
        });

        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    async function _decryptAndShow(div, encryptedContent, key) {
        try {
            var txt = await CRYPTO.decryptMessage(encryptedContent, key);
            if (txt) div.querySelector(".message-text").textContent = txt;
        } catch (e) { /* ignore decrypt errors */ }
    }

    async function loadGroupSharedKey(groupId, ownerId) {
        const token = localStorage.getItem("token");
        var res = await apiFetch(`/api/groups/${groupId}/members/${ownerId}/shared-key`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status !== 200) return;
        var data = await res.json();
        if (data && data.encrypted_broadcast_key && privateKey) {
            try {
                var raw = await CRYPTO.decryptBroadcastKey(b64dec(data.encrypted_broadcast_key), privateKey);
                groupKeyCache["g:" + ownerId] = await CRYPTO.importBroadcastKey(raw);
            } catch (e) { console.error("loadGroupSharedKey failed:", e); }
        }
    }

    async function syncGroupKeys(groupId) {
        const token = localStorage.getItem("token");
        try {
            var membersRes = await apiFetch(`/api/groups/${groupId}/members`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            var members = await membersRes.json();
            var keysRes = await apiFetch(`/api/groups/${groupId}/members/keys`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            var keys = keysRes.ok ? await keysRes.json() : [];

            for (var i = 0; i < members.length; i++) {
                var m = members[i];
                if (m.user_id === currentUser.id) continue;
                // decrypt their key if we have it stored
                var keyData = keys.find(function(k) { return k.owner_id === m.user_id; });
                if (keyData && keyData.encrypted_broadcast_key && !groupKeyCache["g:" + m.user_id] && privateKey) {
                    try {
                        var raw = await CRYPTO.decryptBroadcastKey(b64dec(keyData.encrypted_broadcast_key), privateKey);
                        groupKeyCache["g:" + m.user_id] = await CRYPTO.importBroadcastKey(raw);
                    } catch (e) { /* ignore */ }
                }
                // always share our key — backend handles duplicates
                if (m.public_key) {
                    await _shareMyGroupKeyDirect(groupId, m.user_id, m.public_key);
                }
            }
        } catch (e) { console.error("syncGroupKeys failed:", e); }
    }

    // ── Update renderUserList to show group users + block button ──
    renderUserList = function(users) {
        // show groups in the list too
        loadMyGroups().then(function(groups) {
            var allItems = [];
            if (groups && groups.length) {
                groups.forEach(function(g) {
                    allItems.push({ _type: "group", id: g.id, name: g.name, member_count: g.member_count, invite_code: g.invite_code });
                });
            }
            users.forEach(function(u) {
                allItems.push(Object.assign({ _type: "user" }, u));
            });
            _renderCombinedList(allItems);
        });
    };

    async function loadMyGroups() {
        const token = localStorage.getItem("token");
        try {
            var res = await apiFetch("/api/groups", { headers: { Authorization: `Bearer ${token}` } });
            return await res.json();
        } catch (e) { return []; }
    }

    function _renderCombinedList(items) {
        const list = $("user-list");
        const empty = $("search-empty");
        list.innerHTML = "";
        if (!items.length) { empty.classList.remove("hidden"); return; }
        empty.classList.add("hidden");

        items.forEach(function(item) {
            if (item._type === "group") {
                var div = document.createElement("div");
                div.className = "user-item";
                div.dataset.groupId = item.id;
                div.innerHTML = `
                    <div class="user-avatar">G</div>
                    <div class="user-item-info">
                        <div class="user-name">${escHtml(item.name)}</div>
                        <div class="user-last-msg">${item.member_count} members</div>
                    </div>
                `;
                div.onclick = function() { openGroupChat({ id: item.id, name: item.name, member_count: item.member_count }); };
                list.appendChild(div);
            } else {
                userCache[item.id] = item;
                var div = document.createElement("div");
                div.className = "user-item" + (activeChatId === item.id ? " active" : "");
                div.dataset.userId = item.id;
                var letter = avatarLetter(item.username);
                var unread = unreadCounts[item.id] || 0;
                var statusText, statusClass;
                var actionBtn = "";
                if (item.is_online) {
                    statusText = 'Online'; statusClass = 'status-online';
                } else if (item.last_seen) {
                    var d = new Date(item.last_seen);
                    statusText = `Last seen: ${d.toLocaleDateString()} ${d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}`;
                    statusClass = 'status-offline';
                } else if (item.permission_status === "approved") {
                    statusText = "Can chat"; statusClass = "status-approved";
                } else if (item.permission_status === "pending") {
                    statusText = "Pending"; statusClass = "status-pending";
                } else if (item.permission_status === "rejected") {
                    statusText = "Rejected"; statusClass = "status-rejected";
                } else {
                    statusText = "Request"; statusClass = "status-none";
                    actionBtn = `<button class="btn-request" data-id="${item.id}">+</button>`;
                }
                var badge = unread ? `<span class="unread-badge">${unread}</span>` : "";
                var onlineDot = item.is_online ? '<span class="online-dot"></span>' : "";

                div.innerHTML = `
                    <div class="user-avatar">${letter}${badge}${onlineDot}</div>
                    <div class="user-item-info">
                        <div class="user-name">${escHtml(item.username)}</div>
                        <div class="user-last-msg ${statusClass}">${statusText}</div>
                    </div>
                    ${actionBtn}
                `;

                var reqBtn = div.querySelector(".btn-request");
                if (reqBtn) {
                    reqBtn.onclick = function(e) { e.stopPropagation(); requestPermission(item.id, item.username); };
                }
                if (item.permission_status === "approved") {
                    div.onclick = function() { openChat(item, div); };
                    div.addEventListener("contextmenu", function(e) {
                        e.preventDefault();
                        if (confirm("Block " + item.username + "?")) blockUser(item.id);
                    });
                } else if (item.permission_status === "pending" || item.permission_status === "none" || item.permission_status === "rejected") {
                    div.style.cursor = "default";
                    div.onclick = null;
                }
                list.appendChild(div);
            }
        });
    }

    // ── System message for new features ──
    var _origAddSystem = addSystemMessage;
    addSystemMessage = function(text) {
        const container = $("messages");
        if (!container) return;
        const div = document.createElement("div");
        div.className = "message system";
        div.textContent = text;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    };
})();

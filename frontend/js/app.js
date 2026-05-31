(function () {
    const $ = (id) => document.getElementById(id);

    function redirectOnAuthError(res) {
        if (res.status === 401 || res.status === 403) {
            localStorage.clear();
            location.reload();
            return true;
        }
        return false;
    }

    async function apiFetch(url, options = {}) {
        const res = await fetch(url, options);
        if (redirectOnAuthError(res)) throw new Error("Session expired");
        return res;
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
        document.getElementById(`tab-${tab}`).classList.add("active");
        document.getElementById(`tab-content-${tab}`).classList.remove("hidden");
        if (tab === "invites") loadIncomingRequests();
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
            localStorage.setItem("password", password);
            await initApp(data.token);
        } catch (e) {
            btn.disabled = false;
            errEl.textContent = e.message;
            errEl.classList.remove("hidden");
        }
    };

    window.handleLogout = function () {
        MESSENGER_SOCKET.disconnect();
        localStorage.clear();
        location.reload();
    };

    // ── initialise app after login ──
    async function initApp(token) {
        appToken = token;
        const res = await apiFetch("/api/auth/me", {
            headers: { Authorization: `Bearer ${token}` },
        });
        currentUser = await res.json();

        const storedPass = localStorage.getItem("password");

        if (currentUser.encrypted_private_key && storedPass) {
            try {
                const encBlob = b64dec(currentUser.encrypted_private_key);
                privateKey = await CRYPTO.decryptPrivateKey(encBlob, storedPass);
            } catch (e) {
                console.error("decrypt private key failed:", e);
            }
        }
        if (currentUser.broadcast_key) {
            myBroadcastKey = await CRYPTO.importBroadcastKey(b64dec(currentUser.broadcast_key));
        }

        showPage("main-page");
        $("user-greeting").textContent = currentUser.username;
        await loadUsers();
        await fetchUnreadCounts();
        loadIncomingRequests();
        connectSocket(token);
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
                ? "✓ Вы делитесь ключом доступа"
                : "✗ Вы не делитесь ключом доступа";

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
        MESSENGER_SOCKET.connect(token, {
            onMessage: handleIncomingMessage,
            onTyping: handleTypingIndicator,
            onKeyShared: ({ owner_id }) => {
                if (owner_id === activeChatId) {
                    loadSharedKey(owner_id);
                    renderMessages(owner_id);
                    refreshKeyStatusFor(owner_id);
                }
            },
            onKeyRevoked: ({ owner_id }) => {
                delete broadcastKeyCache[owner_id];
                if (activeChatId === owner_id) {
                    renderMessages(owner_id);
                    refreshKeyStatusFor(owner_id);
                }
            },
            onPermissionRequest: (data) => {
                loadIncomingRequests();
                flash($("tab-invites"));
            },
            onPermissionResponse: (data) => {
                loadUsers();
                if (data.status === "approved" && activeChatId === data.owner_id) {
                    loadSharedKey(data.owner_id);
                }
            },
            onKeyRequested: (data) => {
                // re-render messages if in active chat with the requester
                if (activeChatId === data.requester_id) {
                    renderMessages(activeChatId);
                }
            },
        });
    }

    // ── permission requests ──
    async function loadIncomingRequests() {
        const token = localStorage.getItem("token");
        try {
            const res = await apiFetch("/api/permissions/incoming", {
                headers: { Authorization: `Bearer ${token}` },
            });
            const requests = await res.json();
            renderIncomingRequests(requests);
        } catch (e) {
            console.error("loadIncomingRequests failed:", e);
        }
    }

    function renderIncomingRequests(requests) {
        const container = $("requests-list");
        const countEl = $("invite-count");
        const empty = $("invites-empty");
        if (!requests.length) {
            countEl.classList.add("hidden");
            if (empty) empty.classList.remove("hidden");
            if (container) container.innerHTML = "";
            return;
        }
        countEl.textContent = requests.length;
        countEl.classList.remove("hidden");
        if (empty) empty.classList.add("hidden");
        container.innerHTML = "";
        requests.forEach((r) => {
            const div = document.createElement("div");
            div.className = "request-item";
            div.innerHTML = `
                <span class="request-user">${escHtml(r.requester_username)} wants to chat</span>
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
            if (u.permission_status === "approved") {
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
                <div class="user-avatar">${letter}${badge}</div>
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
        if (!target || !target.public_key || !currentUser || !currentUser.broadcast_key) {
            console.warn("shareMyKey: missing target or keys for", userId);
            return false;
        }
        try {
            const encrypted = await CRYPTO.encryptBroadcastKey(
                b64dec(currentUser.broadcast_key),
                b64dec(target.public_key)
            );
            MESSENGER_SOCKET.shareKey(userId, encrypted);
            broadcastKeyCache[userId] = broadcastKeyCache[userId] || null;
            return true;
        } catch (e) {
            console.error("shareMyKey: encryption failed", e);
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
        } catch (e) {
            console.error("requestKeyAccess failed:", e);
        }
    }

    // ── open chat ──
    async function openChat(user, el) {
        activeChatId = user.id;

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
                ? "✓ Вы делитесь ключом доступа"
                : "✗ Вы не делитесь ключом доступа";

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
            if (data && data.encrypted_broadcast_key && privateKey) {
                try {
                    const raw = await CRYPTO.decryptBroadcastKey(b64dec(data.encrypted_broadcast_key), privateKey);
                    broadcastKeyCache[userId] = await CRYPTO.importBroadcastKey(raw);
                    return;
                } catch (e) {
                    console.error("decrypt shared key:", e);
                }
            }
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

            const text = document.createElement("div");
            text.className = "message-text";

            let displayText;
            if (isMine && myBroadcastKey) {
                displayText = await CRYPTO.decryptMessage(msg.encrypted_content, myBroadcastKey);
            } else if (broadcastKeyCache[peerId]) {
                displayText = await CRYPTO.decryptMessage(msg.encrypted_content, broadcastKeyCache[peerId]);
            }
            if (!displayText) displayText = "[Encrypted message]";

            text.textContent = displayText;
            div.appendChild(text);

            const time = document.createElement("div");
            time.className = "message-time";
            const readMark = isMine ? (msg.is_read ? " ✓✓" : " ✓") : "";
            time.textContent = new Date(msg.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + readMark;

            container.appendChild(div);
        }
        container.scrollTop = container.scrollHeight;
    }

    async function handleIncomingMessage(data) {
        if (data.type === "system") {
            // system messages: just re-render if in active chat
            const peerId = data.sender_id === currentUser.id ? data.receiver_id : data.sender_id;
            if (activeChatId === peerId) {
                await renderMessages(peerId);
            }
            return;
        }
        const peerId = data.sender_id === currentUser.id ? data.receiver_id : data.sender_id;
        if (activeChatId === peerId) {
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
        } else {
            unreadCounts[peerId] = (unreadCounts[peerId] || 0) + 1;
            const senderName = data.sender_username || userCache[peerId]?.username || "";
            updateTitle(senderName);
            fetchUnreadCounts();
        }
    }

    // ── send message ──
    window.sendMessage = async function () {
        const input = $("message-input");
        const text = input.value.trim();
        if (!text || !activeChatId) return;
        input.value = "";

        const token = localStorage.getItem("token");

        // share MY key with target if not yet shared
        const hasMyKeyRes = await apiFetch(`/api/messages/${activeChatId}/has-my-key`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        const hasMyKey = await hasMyKeyRes.json();
        if (!hasMyKey) {
            const shared = await shareMyKey(activeChatId);
            if (!shared) {
                console.warn("sendMessage: could not share key, message not sent");
                return;
            }
        }

        const encrypted = await CRYPTO.encryptMessage(text, myBroadcastKey);
        MESSENGER_SOCKET.sendMessage(activeChatId, encrypted);
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

    // ── autorun ──
    const savedToken = localStorage.getItem("token");
    if (savedToken) {
        initApp(savedToken).catch(() => {
            localStorage.clear();
            showPage("login-page");
        });
    }
})();

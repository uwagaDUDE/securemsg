const MESSENGER_SOCKET = (() => {
    let socket = null;

    function _isConnected() {
        return socket && socket.connected;
    }

    function connect(token, handlers) {
        console.log("[socket] creating io() with tokenLen:", token ? token.length : 0);
        socket = io("", {
            auth: { token },
            transports: ["websocket", "polling"],
            reconnection: true,
            reconnectionAttempts: 10,
            reconnectionDelay: 1000,
            reconnectionDelayMax: 10000,
        });

        socket.on("connect", () => {
            console.log("[socket] connected, transport:", socket.io.engine.transport.name);
            if (handlers.onConnect) handlers.onConnect();
        });

        socket.io.on("reconnect_attempt", (attempt) => {
            console.log("[socket] reconnect attempt #", attempt);
        });

        socket.io.on("reconnect", () => {
            console.log("[socket] reconnected successfully");
            if (handlers.onConnect) handlers.onConnect();
        });

        socket.io.on("reconnect_error", (err) => {
            console.error("[socket] reconnect error:", err.message);
        });

        socket.io.on("reconnect_failed", () => {
            console.error("[socket] reconnect failed after all attempts");
        });

        socket.on("connect_error", async (err) => {
            console.error("[socket] connect_error:", err.message, "type:", err.type, "description:", err.description);
            if (err.message && (err.message.includes("token") || err.message.includes("previous server session"))) {
                try {
                    var token = localStorage.getItem("token");
                    var res = await fetch("/api/auth/refresh", {
                        method: "POST",
                        headers: { "Authorization": "Bearer " + token },
                    });
                    if (res.ok) {
                        var data = await res.json();
                        localStorage.setItem("token", data.token);
                        localStorage.setItem("user_id", data.user_id);
                        socket.auth = { token: data.token };
                        console.log("[socket] token refreshed, will retry");
                    }
                } catch (_) {}
            }
        });

        socket.on("disconnect", (reason) => {
            console.log("[socket] disconnected, reason:", reason);
            if (handlers.onDisconnect) handlers.onDisconnect();
        });

        socket.on("new_message", async (data) => {
            if (handlers.onMessage) await handlers.onMessage(data);
        });

        socket.on("typing", (data) => {
            if (handlers.onTyping) handlers.onTyping(data);
        });

        socket.on("key_shared", async (data) => {
            if (handlers.onKeyShared) await handlers.onKeyShared(data);
        });

        socket.on("key_revoked", async (data) => {
            if (handlers.onKeyRevoked) await handlers.onKeyRevoked(data);
        });

        socket.on("permission_request", async (data) => {
            if (handlers.onPermissionRequest) await handlers.onPermissionRequest(data);
        });

        socket.on("permission_response", async (data) => {
            if (handlers.onPermissionResponse) await handlers.onPermissionResponse(data);
        });

        socket.on("key_requested", async (data) => {
            if (handlers.onKeyRequested) await handlers.onKeyRequested(data);
        });

        socket.on("user_status", (data) => {
            if (handlers.onUserStatus) handlers.onUserStatus(data);
        });

        socket.on("message_edited", (data) => {
            if (handlers.onMessageEdited) handlers.onMessageEdited(data);
        });

        socket.on("message_deleted", (data) => {
            if (handlers.onMessageDeleted) handlers.onMessageDeleted(data);
        });

        socket.on("reaction_updated", (data) => {
            if (handlers.onReactionUpdated) handlers.onReactionUpdated(data);
        });

        socket.on("channel_message", (data) => {
            if (handlers.onChannelMessage) handlers.onChannelMessage(data);
        });

        socket.on("group_message", (data) => {
            if (handlers.onGroupMessage) handlers.onGroupMessage(data);
        });

        socket.on("group_key_shared", (data) => {
            if (handlers.onGroupKeyShared) handlers.onGroupKeyShared(data);
        });

        socket.on("group_key_revoked", (data) => {
            if (handlers.onGroupKeyRevoked) handlers.onGroupKeyRevoked(data);
        });

        socket.on("group_member_joined", (data) => {
            if (handlers.onGroupMemberJoined) handlers.onGroupMemberJoined(data);
        });

        socket.on("group_member_left", (data) => {
            if (handlers.onGroupMemberLeft) handlers.onGroupMemberLeft(data);
        });

        socket.on("group_member_removed", (data) => {
            if (handlers.onGroupMemberRemoved) handlers.onGroupMemberRemoved(data);
        });
    }

    function joinRoom(targetId) {
        if (_isConnected()) socket.emit("join_room", { target_id: targetId });
    }

    function joinGroupRoom(groupId) {
        if (_isConnected()) socket.emit("join_room", { group_id: groupId });
    }

    function joinChannelRoom(channelId) {
        if (_isConnected()) socket.emit("join_room", { channel_id: channelId });
    }

    function sendMessage(receiverId, encryptedContent, attachmentIds, ackCallback) {
        if (!socket) {
            console.error("[socket] sendMessage: socket is null");
            if (ackCallback) ackCallback({ error: "not_initialized", detail: "Socket not initialized" });
            return;
        }
        console.log("[socket] sendMessage, socket.connected:", socket.connected, "transport:", socket.io && socket.io.engine ? socket.io.engine.transport.name : "unknown");
        if (!_isConnected()) {
            console.warn("[socket] sendMessage: socket not connected, trying connect...");
            socket.connect();
            if (ackCallback) ackCallback({ error: "not_connected", detail: "Socket is not connected. Please wait and try again." });
            return;
        }
        socket.emit("send_message", { receiver_id: receiverId, encrypted_content: encryptedContent, attachment_ids: attachmentIds || [] }, ackCallback || null);
    }

    function sendTyping(receiverId, isTyping) {
        if (_isConnected()) {
            socket.emit("typing", { receiver_id: receiverId, is_typing: isTyping });
        }
    }

    function shareKey(targetId, encryptedBroadcastKey) {
        if (_isConnected()) {
            const b64 = btoa(String.fromCharCode(...new Uint8Array(encryptedBroadcastKey)));
            socket.emit("share_key", { target_id: targetId, encrypted_broadcast_key: b64 });
        }
    }

    function shareGroupKey(groupId, targetId, encryptedBroadcastKey) {
        if (!_isConnected()) {
            console.error("Cannot share group key: socket disconnected");
            return false;
        }
        const b64 = btoa(String.fromCharCode(...new Uint8Array(encryptedBroadcastKey)));
        socket.emit("share_group_key", { group_id: groupId, target_id: targetId, encrypted_broadcast_key: b64 });
        return true;
    }

    function notifyPermissionRequested(ownerId) {
        if (_isConnected()) socket.emit("permission_requested", { owner_id: ownerId });
    }

    function notifyPermissionResponded(requesterId, status) {
        if (_isConnected()) socket.emit("permission_responded", { requester_id: requesterId, status });
    }

    function setOnlineStatus(isOnline) {
        if (_isConnected()) socket.emit("set_online_status", { is_online: isOnline });
    }

    function disconnect() {
        if (socket) {
            socket.disconnect();
            socket = null;
        }
    }

    return {
        connect, disconnect, joinRoom, joinGroupRoom, joinChannelRoom,
        sendMessage, sendTyping, shareKey, shareGroupKey,
        notifyPermissionRequested, notifyPermissionResponded, setOnlineStatus,
    };
})();

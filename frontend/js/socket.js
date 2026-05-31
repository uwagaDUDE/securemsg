const MESSENGER_SOCKET = (() => {
    let socket = null;
    let connected = false;

    function connect(token, handlers) {
        socket = io("", {
            auth: { token },
            transports: ["websocket"],
        });

        socket.on("connect", () => {
            connected = true;
            console.log("Socket connected");
            if (handlers.onConnect) handlers.onConnect();
        });

        socket.on("disconnect", () => {
            connected = false;
            console.log("Socket disconnected");
            if (handlers.onDisconnect) handlers.onDisconnect();
        });

        socket.on("new_message", (data) => {
            if (handlers.onMessage) handlers.onMessage(data);
        });

        socket.on("typing", (data) => {
            if (handlers.onTyping) handlers.onTyping(data);
        });

        socket.on("key_shared", (data) => {
            if (handlers.onKeyShared) handlers.onKeyShared(data);
        });

        socket.on("key_revoked", (data) => {
            if (handlers.onKeyRevoked) handlers.onKeyRevoked(data);
        });

        socket.on("permission_request", (data) => {
            if (handlers.onPermissionRequest) handlers.onPermissionRequest(data);
        });

        socket.on("permission_response", (data) => {
            if (handlers.onPermissionResponse) handlers.onPermissionResponse(data);
        });

        socket.on("key_requested", (data) => {
            if (handlers.onKeyRequested) handlers.onKeyRequested(data);
        });

        socket.on("user_status", (data) => {
            if (handlers.onUserStatus) handlers.onUserStatus(data);
        });
    }

    function joinRoom(targetId) {
        if (socket) socket.emit("join_room", { target_id: targetId });
    }

    function sendMessage(receiverId, encryptedContent) {
        if (socket) {
            socket.emit("send_message", { receiver_id: receiverId, encrypted_content: encryptedContent });
        }
    }

    function sendTyping(receiverId, isTyping) {
        if (socket) {
            socket.emit("typing", { receiver_id: receiverId, is_typing: isTyping });
        }
    }

    function shareKey(targetId, encryptedBroadcastKey) {
        if (socket) {
            const b64 = btoa(String.fromCharCode(...new Uint8Array(encryptedBroadcastKey)));
            socket.emit("share_key", { target_id: targetId, encrypted_broadcast_key: b64 });
        }
    }

    function notifyPermissionRequested(ownerId) {
        if (socket) socket.emit("permission_requested", { owner_id: ownerId });
    }

    function notifyPermissionResponded(requesterId, status) {
        if (socket) socket.emit("permission_responded", { requester_id: requesterId, status });
    }

    function disconnect() {
        if (socket) {
            socket.disconnect();
            socket = null;
            connected = false;
        }
    }

    return {
        connect, disconnect, joinRoom, sendMessage, sendTyping, shareKey,
        notifyPermissionRequested, notifyPermissionResponded,
    };
})();

import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { io } from "socket.io-client";
import { refreshToken } from "../utils/api";

const SocketContext = createContext(null);

export function useSocket() {
  return useContext(SocketContext);
}

export function SocketProvider({ children, onMessage, onTyping, onUserStatus, onKeyShared, onKeyRevoked,
  onPermissionRequest, onPermissionResponse, onKeyRequested, onMessageEdited, onMessageDeleted,
  onMessagesRead, onReactionUpdated, onChannelMessage, onGroupMessage, onGroupKeyShared,
  onGroupKeyRevoked, onGroupMemberJoined, onGroupMemberLeft, onGroupMemberRemoved }) {

  const [connected, setConnected] = useState(false);
  const socketRef = useRef(null);
  const cbs = useRef({ onMessage, onTyping, onUserStatus, onKeyShared, onKeyRevoked,
    onPermissionRequest, onPermissionResponse, onKeyRequested,
    onMessageEdited, onMessageDeleted, onMessagesRead, onReactionUpdated,
    onChannelMessage, onGroupMessage, onGroupKeyShared, onGroupKeyRevoked,
    onGroupMemberJoined, onGroupMemberLeft, onGroupMemberRemoved });
  cbs.current = { onMessage, onTyping, onUserStatus, onKeyShared, onKeyRevoked,
    onPermissionRequest, onPermissionResponse, onKeyRequested,
    onMessageEdited, onMessageDeleted, onMessagesRead, onReactionUpdated,
    onChannelMessage, onGroupMessage, onGroupKeyShared, onGroupKeyRevoked,
    onGroupMemberJoined, onGroupMemberLeft, onGroupMemberRemoved };

  const connect = useCallback((token) => {
    if (socketRef.current?.connected) return;

    const socket = io("", {
      auth: { token },
      transports: ["websocket", "polling"],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 10000,
    });

    socket.on("connect", () => setConnected(true));

    socket.on("connect_error", async (err) => {
      if (err.message && (err.message.includes("token") || err.message.includes("previous server session"))) {
        const newToken = await refreshToken();
        if (newToken) socket.auth = { token: newToken };
      }
    });

    socket.on("disconnect", () => setConnected(false));

    socket.on("new_message", (data) => cbs.current.onMessage?.(data));
    socket.on("typing", (data) => cbs.current.onTyping?.(data));
    socket.on("user_status", (data) => cbs.current.onUserStatus?.(data));
    socket.on("key_shared", (data) => cbs.current.onKeyShared?.(data));
    socket.on("key_revoked", (data) => cbs.current.onKeyRevoked?.(data));
    socket.on("permission_request", (data) => cbs.current.onPermissionRequest?.(data));
    socket.on("permission_response", (data) => cbs.current.onPermissionResponse?.(data));
    socket.on("key_requested", (data) => cbs.current.onKeyRequested?.(data));
    socket.on("message_edited", (data) => cbs.current.onMessageEdited?.(data));
    socket.on("message_deleted", (data) => cbs.current.onMessageDeleted?.(data));
    socket.on("messages_read", (data) => cbs.current.onMessagesRead?.(data));
    socket.on("reaction_updated", (data) => cbs.current.onReactionUpdated?.(data));
    socket.on("new_channel_message", (data) => cbs.current.onChannelMessage?.(data));
    socket.on("new_group_message", (data) => cbs.current.onGroupMessage?.(data));
    socket.on("group_key_shared", (data) => cbs.current.onGroupKeyShared?.(data));
    socket.on("group_key_revoked", (data) => cbs.current.onGroupKeyRevoked?.(data));
    socket.on("group_member_joined", (data) => cbs.current.onGroupMemberJoined?.(data));
    socket.on("group_member_left", (data) => cbs.current.onGroupMemberLeft?.(data));
    socket.on("group_member_removed", (data) => cbs.current.onGroupMemberRemoved?.(data));

    socketRef.current = socket;
  }, []);

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
      setConnected(false);
    }
  }, []);

  const emit = useCallback((event, data, ack) => {
    if (socketRef.current?.connected) {
      socketRef.current.emit(event, data, ack);
    }
  }, []);

  const joinRoom = useCallback((data) => {
    if (socketRef.current?.connected) {
      socketRef.current.emit("join_room", data);
    }
  }, []);

  useEffect(() => {
    return () => disconnect();
  }, [disconnect]);

  const getSocket = useCallback(() => socketRef.current, []);

  const value = { connected, connect, disconnect, emit, joinRoom, getSocket };

  return <SocketContext.Provider value={value}>{children}</SocketContext.Provider>;
}

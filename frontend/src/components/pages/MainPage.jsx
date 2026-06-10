import { useEffect, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";
import { useSocket } from "../../context/SocketContext";
import { useChat } from "../../context/ChatContext";
import { apiFetch } from "../../utils/api";
import { b64dec, b64enc } from "../../utils/helpers";
import { decryptMessage, importBroadcastKey, encryptBroadcastKey, decryptBroadcastKey } from "../../utils/crypto";
import Sidebar from "../layout/Sidebar";
import ChatView from "../layout/ChatView";

export default function MainPage() {
  const { t } = useTranslation();
  const { user, privateKey, myBroadcastKey } = useAuth();
  const { connect: socketConnect } = useSocket();
  const chat = useChat();
  const [activeTab, setActiveTab] = useState("contacts");

  const loadUsers = useCallback(async () => {
    const res = await apiFetch("/api/v1/users");
    if (res.ok) {
      const data = await res.json();
      chat.setUsers(data);
    }
  }, []);

  const loadChannels = useCallback(async () => {
    const res = await apiFetch("/api/v1/channels");
    if (res.ok) {
      const data = await res.json();
      chat.setChannels(data);
    }
  }, []);

  const loadGroups = useCallback(async () => {
    const res = await apiFetch("/api/v1/groups");
    if (res.ok) {
      const data = await res.json();
      chat.setGroups(data);
    }
  }, []);

  const fetchUnreadCounts = useCallback(async () => {
    const res = await apiFetch("/api/v1/messages/unread-counts");
    if (res.ok) {
      const data = await res.json();
      chat.setUnreadCounts(data);
    }
  }, []);

  useEffect(() => {
    if (user) {
      loadUsers();
      loadChannels();
      loadGroups();
      fetchUnreadCounts();
    }
  }, [user]);

  const { connected, getSocket } = useSocket();

  useEffect(() => {
    if (user) {
      socketConnect(localStorage.getItem("token"));
    }
  }, [user, socketConnect]);

  useEffect(() => {
    const socket = getSocket();
    if (!socket) return;

    function onNewMessage(data) {
      const isActive = chat.activeChatId === data.receiver_id || chat.activeChatId === data.sender_id;
      if (isActive) {
        chat.setMessages((prev) => [...prev, data]);
      }
    }

    function onNewGroupMessage(data) {
      if (chat.activeGroupId !== data.group_chat_id) return;
      if (data.sender_id === user?.id) return;
      (async () => {
        if (data.encrypted_content && data.sender_id !== user?.id) {
          const key = chat.groupSharedKeys[data.group_chat_id]?.[data.sender_id] ||
            await fetchGroupSharedKey(data.group_chat_id, data.sender_id);
          if (key) {
            const decrypted = await decryptMessage(data.encrypted_content, key);
            if (decrypted) data = { ...data, content: decrypted };
          }
        }
        chat.setMessages((prev) => [...prev, data]);
      })();
    }

    function onNewChannelMessage(data) {
      if (chat.activeChannelId === data.channel_id) {
        chat.setMessages((prev) => [...prev, data]);
      }
    }

    function onGroupKeyShared(data) {
      if (data.owner_id !== user?.id && data.target_id === user?.id) {
        fetchGroupSharedKey(data.group_id, data.owner_id);
      }
    }

    function onMessageEdited(data) {
      chat.setMessages(prev => prev.map(m =>
        m.id === data.message_id
          ? { ...m,
              encrypted_content: data.encrypted_content ?? m.encrypted_content,
              content: data.content ?? m.content,
              edited_at: data.edited_at }
          : m
      ));
    }

    function onMessageDeleted(data) {
      if (data.delete_for_all) {
        chat.setMessages(prev => prev.filter(m => m.id !== data.message_id));
      }
    }

    function onReactionUpdated(data) {
      chat.setMessages(prev => prev.map(m =>
        m.id === data.message_id ? { ...m, reactions: data.reactions } : m
      ));
    }

    function onGroupMemberJoined(data) {
      if (data.user_id === user?.id) return;
      const g = chat.groups.find((gr) => gr.id === data.group_id);
      if (!g) return;
      apiFetch(`/api/v1/groups/${data.group_id}/members`).then((res) => {
        if (!res.ok) return;
        res.json().then((members) => {
          const m = members.find((mm) => mm.user_id === data.user_id);
          if (m?.public_key) {
            shareMyKeyWith(data.group_id, data.user_id, m.public_key);
          }
        });
      });
    }

    socket.on("new_message", onNewMessage);
    socket.on("new_group_message", onNewGroupMessage);
    socket.on("new_channel_message", onNewChannelMessage);
    socket.on("group_key_shared", onGroupKeyShared);
    socket.on("group_member_joined", onGroupMemberJoined);
    socket.on("message_edited", onMessageEdited);
    socket.on("message_deleted", onMessageDeleted);
    socket.on("reaction_updated", onReactionUpdated);

    return () => {
      socket.off("new_message", onNewMessage);
      socket.off("new_group_message", onNewGroupMessage);
      socket.off("new_channel_message", onNewChannelMessage);
      socket.off("group_key_shared", onGroupKeyShared);
      socket.off("group_member_joined", onGroupMemberJoined);
      socket.off("message_edited", onMessageEdited);
      socket.off("message_deleted", onMessageDeleted);
      socket.off("reaction_updated", onReactionUpdated);
    };
  }, [chat.activeChatId, chat.activeGroupId, chat.activeChannelId, connected, getSocket, user?.id, chat.groupSharedKeys]);

  async function fetchGroupSharedKey(groupId, ownerId) {
    const cached = chat.groupSharedKeys[groupId]?.[ownerId];
    if (cached) return cached;
    try {
      const res = await apiFetch(`/api/v1/groups/${groupId}/shared-key/${ownerId}`);
      if (res.ok) {
        const data = await res.json();
        if (data?.encrypted_broadcast_key && privateKey) {
          const encKey = b64dec(data.encrypted_broadcast_key);
          const rawKey = await decryptBroadcastKey(encKey, privateKey);
          const key = await importBroadcastKey(rawKey);
          chat.setGroupSharedKey(groupId, ownerId, key);
          return key;
        }
      }
    } catch (e) {
      console.error("[group key] fetch failed:", e);
    }
    return null;
  }

  async function shareMyKeyWith(groupId, targetId, targetPublicKeyB64) {
    if (!myBroadcastKey) return;
    try {
      const rawBk = await crypto.subtle.exportKey("raw", myBroadcastKey);
      const encrypted = await encryptBroadcastKey(rawBk, b64dec(targetPublicKeyB64));
      const socket = getSocket();
      if (socket) {
        socket.emit("share_group_key", {
          group_id: groupId,
          target_id: targetId,
          encrypted_broadcast_key: b64enc(new Uint8Array(encrypted)),
        });
      }
    } catch (e) {
      console.error("[group key] share failed:", e);
    }
  }

  async function ensureGroupKeys(groupId) {
    try {
      const res = await apiFetch(`/api/v1/groups/${groupId}/members`);
      if (!res.ok) return;
      const members = await res.json();
      const socket = getSocket();
      for (const m of members) {
        if (m.user_id === user?.id) continue;
        if (m.public_key && socket) {
          shareMyKeyWith(groupId, m.user_id, m.public_key);
        }
        fetchGroupSharedKey(groupId, m.user_id);
      }
    } catch (e) {
      console.error("[group key] ensure failed:", e);
    }
  }

  function handleSelectChat(u) {
    chat.setActiveChatId(u.id);
    chat.setActiveChannelId(null);
    chat.setActiveGroupId(null);
  }

  function handleSelectChannel(ch) {
    chat.setActiveChannelId(ch.id);
    chat.setActiveChatId(null);
    chat.setActiveGroupId(null);
  }

  function handleSelectGroup(g) {
    chat.setActiveGroupId(g.id);
    chat.setActiveChatId(null);
    chat.setActiveChannelId(null);
    ensureGroupKeys(g.id);
  }

  return (
    <div className="app-layout">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        onSelectChat={handleSelectChat}
        onSelectChannel={handleSelectChannel}
        onSelectGroup={handleSelectGroup}
      />
      <div className="main-content">
        {(!chat.activeChatId && !chat.activeChannelId && !chat.activeGroupId) ? (
          <div className="no-chat">
            <div className="no-chat-content">
              <img src="/favicon.png" alt="" className="no-chat-logo" />
              <h2>Secure Messenger</h2>
              <p>{t("chat.select_contact")}</p>
            </div>
          </div>
        ) : (
          <ChatView />
        )}
      </div>
    </div>
  );
}

import { useEffect, useState, useCallback, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";
import { useSocket } from "../../context/SocketContext";
import { useChat } from "../../context/ChatContext";
import { apiFetch, uploadAttachment } from "../../utils/api";
import { encryptMessage, decryptMessage } from "../../utils/crypto";
import { getPendingMessages, savePendingMessage, removePendingMessage } from "../../utils/pendingMessages";
import { avatarBg } from "../../utils/helpers";
import Message from "../chat/Message";
import ContextMenu from "../chat/ContextMenu";
import EditModal from "../modals/EditModal";
import ForwardModal from "../modals/ForwardModal";
import DeleteConfirmModal from "../modals/DeleteConfirmModal";

export default function ChatView() {
  const { t } = useTranslation();
  const { user, myBroadcastKey } = useAuth();
  const socket = useSocket();
  const chat = useChat();
  const { messages, setMessages } = chat;

  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [contextMenu, setContextMenu] = useState(null);
  const [editTarget, setEditTarget] = useState(null);
  const [forwardTarget, setForwardTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [showInvite, setShowInvite] = useState(false);
  const [copied, setCopied] = useState(false);
  const [attachmentPreviews, setAttachmentPreviews] = useState([]);

  const fileInputRef = useRef(null);
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // ── Active entity info ───────────────────────────────────────
  const activeUser = chat.activeChatId
    ? chat.users.find(u => u.id === chat.activeChatId)
    : null;
  const activeGroup = chat.activeGroupId
    ? chat.groups.find(g => g.id === chat.activeGroupId)
    : null;
  const activeChannel = chat.activeChannelId
    ? chat.channels.find(ch => ch.id === chat.activeChannelId)
    : null;

  const chatTitle = activeUser?.username
    || activeGroup?.name
    || (activeChannel ? "# " + activeChannel.name : "");

  const chatAvatarLetter = chatTitle.replace(/^# /, "").charAt(0).toUpperCase() || "?";
  const chatAvatarColor = avatarBg(chatTitle.replace(/^# /, ""));

  const statusText = activeUser
    ? (activeUser.is_online
        ? t("chat.online")
        : activeUser.last_seen
          ? formatLastSeen(activeUser.last_seen)
          : "")
    : activeGroup
      ? `${activeGroup.member_count || ""} ${t("chat.members")}`
      : activeChannel
        ? t("chat.channel")
        : "";

  const isOnline = !!activeUser?.is_online;

  const currentInviteCode = activeGroup?.invite_code || activeChannel?.invite_code || null;
  const isOwner = (activeGroup?.owner_id === user?.id) || (activeChannel?.owner_id === user?.id);

  // ── Load messages ────────────────────────────────────────────
  const loadMessages = useCallback(async () => {
    if (!chat.activeChatId && !chat.activeGroupId && !chat.activeChannelId) return;
    setLoading(true);
    let url;
    if (chat.activeChatId) url = `/api/v1/messages/${chat.activeChatId}`;
    else if (chat.activeGroupId) url = `/api/v1/groups/${chat.activeGroupId}/messages`;
    else if (chat.activeChannelId) url = `/api/v1/channels/${chat.activeChannelId}/messages`;

    let merged = [];
    try {
      const res = await apiFetch(url);
      if (res.ok) {
        const data = await res.json();
        for (const msg of data) {
          if (!msg.encrypted_content) continue;
          if (msg.sender_id === user?.id || chat.activeChatId) {
            if (myBroadcastKey) {
              const dec = await decryptMessage(msg.encrypted_content, myBroadcastKey);
              if (dec) msg.content = dec;
            }
          } else if (chat.activeGroupId) {
            const key = chat.groupSharedKeys[chat.activeGroupId]?.[msg.sender_id];
            if (key) {
              const dec = await decryptMessage(msg.encrypted_content, key);
              if (dec) msg.content = dec;
            }
          }
        }
        merged = data;
        if (chat.activeChatId) socket.joinRoom({ target_id: chat.activeChatId });
        if (chat.activeGroupId) socket.joinRoom({ group_id: chat.activeGroupId });
        if (chat.activeChannelId) socket.joinRoom({ channel_id: chat.activeChannelId });
      }
    } catch (_) {}

    const pending = getPendingMessages().filter(m => {
      if (m.type === "user") return m.receiver_id === chat.activeChatId;
      if (m.type === "group") return m.group_id === chat.activeGroupId;
      if (m.type === "channel") return m.channel_id === chat.activeChannelId;
      return false;
    });
    merged = [...merged, ...pending];
    merged.sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
    setMessages(merged);
    setLoading(false);
  }, [chat.activeChatId, chat.activeGroupId, chat.activeChannelId, myBroadcastKey]);

  useEffect(() => { loadMessages(); }, [loadMessages]);

  useEffect(() => {
    if (!chat.activeGroupId) return;
    const keys = chat.groupSharedKeys[chat.activeGroupId];
    if (!keys) return;
    (async () => {
      let changed = false;
      for (const msg of messages) {
        if (msg.content || !msg.encrypted_content) continue;
        const key = keys[msg.sender_id];
        if (key) {
          const dec = await decryptMessage(msg.encrypted_content, key);
          if (dec) { msg.content = dec; changed = true; }
        }
      }
      if (changed) setMessages([...messages]);
    })();
  }, [chat.activeGroupId, chat.groupSharedKeys]);

  // ── Auto-grow textarea ───────────────────────────────────────
  function handleTextChange(e) {
    setText(e.target.value);
    const ta = textareaRef.current;
    if (ta) {
      ta.style.height = "auto";
      ta.style.height = Math.min(ta.scrollHeight, 140) + "px";
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── Failed message helper ────────────────────────────────────
  function addFailedMessage(content, encryptedContent, extra) {
    const pendingId = "fail_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
    const failed = {
      pendingId, id: pendingId,
      sender_id: user?.id, sender_username: user?.username,
      content, encrypted_content: encryptedContent,
      created_at: new Date().toISOString(),
      attachments: [], reactions: [], is_read: false, status: "failed",
      ...extra,
    };
    savePendingMessage(failed);
    setMessages(prev => [...prev, failed]);
  }

  // ── Send ─────────────────────────────────────────────────────
  async function sendMessage() {
    if (!text.trim() && attachmentPreviews.length === 0) return;
    if (!chat.activeChatId && !chat.activeGroupId && !chat.activeChannelId) return;

    const msgText = text;
    setText("");
    chat.setReplyTo(null);
    if (textareaRef.current) { textareaRef.current.style.height = "auto"; }

    const hasText = msgText.trim().length > 0;
    let encryptedContent = "";
    if (hasText && myBroadcastKey && (chat.activeChatId || chat.activeGroupId)) {
      encryptedContent = await encryptMessage(msgText, myBroadcastKey);
    } else if (hasText) {
      encryptedContent = msgText;
    }

    const attIds = attachmentPreviews.map(a => a.id);
    const attSnap = attachmentPreviews.map(a => ({ id: a.id, previewUrl: a.url }));
    attachmentPreviews.forEach(a => URL.revokeObjectURL(a.url));
    setAttachmentPreviews([]);

    if (chat.activeChatId) {
      const tempId = Date.now();
      setMessages(prev => [...prev, {
        id: tempId,
        sender_id: user?.id, sender_username: user?.username,
        receiver_id: chat.activeChatId, type: "user",
        content: hasText ? msgText : null,
        encrypted_content: hasText ? encryptedContent : null,
        created_at: new Date().toISOString(),
        attachments: attSnap, reactions: [], is_read: false,
      }]);
      socket.emit("send_message", {
        receiver_id: chat.activeChatId,
        encrypted_content: hasText ? encryptedContent : "",
        attachment_ids: attIds,
      }, ack => {
        if (ack?.error) {
          setMessages(prev => prev.filter(m => m.id !== tempId));
          addFailedMessage(msgText, encryptedContent, { type: "user", receiver_id: chat.activeChatId });
        }
      });
    } else if (chat.activeGroupId) {
      const res = await apiFetch(`/api/v1/groups/${chat.activeGroupId}/send`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ encrypted_content: encryptedContent, attachment_ids: attIds }),
      });
      if (res.ok) {
        const msg = await res.json();
        if (msg.attachments?.length === 0) msg.attachments = attSnap;
        if (hasText) msg.content = msgText;
        setMessages(prev => [...prev, msg]);
      } else {
        addFailedMessage(hasText ? msgText : "", hasText ? encryptedContent : "", { type: "group", group_id: chat.activeGroupId });
      }
    } else if (chat.activeChannelId) {
      const res = await apiFetch(`/api/v1/channels/${chat.activeChannelId}/post`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: hasText ? msgText : "", attachment_ids: attIds }),
      });
      if (res.ok) {
        const msg = await res.json();
        if (msg.attachments?.length === 0) msg.attachments = attSnap;
        setMessages(prev => [...prev, msg]);
      } else {
        addFailedMessage(hasText ? msgText : "", "", { type: "channel", channel_id: chat.activeChannelId });
      }
    }
  }

  // ── Context menu actions ─────────────────────────────────────
  function handleContextMenu(e, msg) {
    setContextMenu({ x: e.clientX, y: e.clientY, message: msg });
  }

  function handleEdit() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    setEditTarget(msg);
  }

  async function handleEditSave(newContent) {
    if (!editTarget) return;
    const msgId = editTarget.id;
    setEditTarget(null);
    try {
      let payload;
      if (myBroadcastKey && (editTarget.type === "user" || editTarget.type === "group")) {
        const enc = await encryptMessage(newContent, myBroadcastKey);
        payload = JSON.stringify({ encrypted_content: enc });
      } else {
        payload = JSON.stringify({ content: newContent });
      }
      const res = await apiFetch(`/api/v1/messages/${msgId}`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: payload,
      });
      if (res.ok) loadMessages();
    } catch (_) {}
  }

  function handleDelete() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    setDeleteTarget(msg);
  }

  async function handleDeleteConfirm(deleteForAll) {
    if (!deleteTarget) return;
    const msg = deleteTarget;
    setDeleteTarget(null);
    try {
      const res = await apiFetch(`/api/v1/messages/${msg.id}?delete_for_all=${deleteForAll ? 1 : 0}`, { method: "DELETE" });
      if (res.ok) loadMessages();
    } catch (_) {}
  }

  function handleReply() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    chat.setReplyTo?.(msg);
  }

  function handleForward() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    setForwardTarget(msg);
  }

  async function handleRetryFailed() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    const enc = msg.encrypted_content || msg.content || "";
    if (msg.type === "user") {
      socket.emit("send_message", { receiver_id: msg.receiver_id, encrypted_content: enc, attachment_ids: [] }, ack => {
        if (ack?.error) return;
        removePendingMessage(msg.pendingId);
        setMessages(prev => prev.filter(m => m.pendingId !== msg.pendingId));
      });
    } else if (msg.type === "group") {
      try {
        const res = await apiFetch(`/api/v1/groups/${msg.group_id}/send`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypted_content: enc, attachment_ids: [] }),
        });
        if (res.ok) { removePendingMessage(msg.pendingId); setMessages(prev => prev.filter(m => m.pendingId !== msg.pendingId)); }
      } catch (_) {}
    } else if (msg.type === "channel") {
      try {
        const res = await apiFetch(`/api/v1/channels/${msg.channel_id}/post`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content: msg.content || "" }),
        });
        if (res.ok) { removePendingMessage(msg.pendingId); setMessages(prev => prev.filter(m => m.pendingId !== msg.pendingId)); }
      } catch (_) {}
    }
  }

  function handleDeleteFailed() {
    const msg = contextMenu?.message;
    if (!msg) return;
    setContextMenu(null);
    removePendingMessage(msg.pendingId);
    setMessages(prev => prev.filter(m => m.pendingId !== msg.pendingId));
  }

  // ── File attach ──────────────────────────────────────────────
  async function handleFileSelect(e) {
    const files = e.target.files;
    if (!files?.length) return;
    const newPreviews = [];
    for (const file of files) {
      try {
        const data = await uploadAttachment(file);
        newPreviews.push({ id: data.id, url: URL.createObjectURL(file), file });
      } catch (_) {}
    }
    setAttachmentPreviews(prev => [...prev, ...newPreviews]);
    e.target.value = "";
  }

  function removeAttachment(index) {
    setAttachmentPreviews(prev => {
      const item = prev[index];
      if (item?.url) URL.revokeObjectURL(item.url);
      return prev.filter((_, i) => i !== index);
    });
  }

  // ── Invite ───────────────────────────────────────────────────
  async function handleCopyInvite() {
    if (!currentInviteCode) return;
    try { await navigator.clipboard.writeText(currentInviteCode); setCopied(true); setTimeout(() => setCopied(false), 2000); } catch {}
  }

  async function handleRegenerateInvite() {
    if (!isOwner) return;
    try {
      const url = chat.activeGroupId
        ? `/api/v1/groups/${chat.activeGroupId}/generate-invite`
        : `/api/v1/channels/${chat.activeChannelId}/generate-invite`;
      const res = await apiFetch(url, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        if (chat.activeGroupId) {
          chat.setGroups(chat.groups.map(g => g.id === chat.activeGroupId ? { ...g, invite_code: data.invite_code } : g));
        } else {
          chat.setChannels(chat.channels.map(ch => ch.id === chat.activeChannelId ? { ...ch, invite_code: data.invite_code } : ch));
        }
        setCopied(false);
      }
    } catch (_) {}
  }

  return (
    <div className="chat-view">
      {/* ── Header ── */}
      <div className="chat-header">
        <div className="chat-h-ava" style={{ background: chatAvatarColor }}>
          {chatAvatarLetter}
        </div>
        <div className="chat-h-info">
          <div className="chat-h-name">{chatTitle}</div>
          {statusText && (
            <div className={`chat-h-status ${isOnline ? "" : "offline"}`}>{statusText}</div>
          )}
        </div>
        <div className="chat-h-actions">
          {(chat.activeGroupId || chat.activeChannelId) && currentInviteCode && (
            <div className="invite-container">
              <button className="invite-btn" onClick={() => setShowInvite(v => !v)} title={t("chat.invite")}>
                🔗
              </button>
              {showInvite && (
                <div className="invite-popup">
                  <div className="invite-code-row">
                    <code className="invite-code">{currentInviteCode}</code>
                    <button className="icon-btn" onClick={handleCopyInvite}>
                      {copied ? "✓" : "📋"}
                    </button>
                  </div>
                  {isOwner && (
                    <button className="invite-regenerate" onClick={handleRegenerateInvite}>
                      {t("chat.regenerate")}
                    </button>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* ── Messages ── */}
      <div className="messages" id="messages" onClick={() => setShowInvite(false)}>
        {loading && (
          <div style={{ textAlign: "center", padding: "24px", color: "var(--text-3)", fontSize: 13 }}>
            {t("common.loading")}
          </div>
        )}
        {messages.map((msg, i) => {
          const prev = i > 0 ? messages[i - 1] : null;
          const timeDiff = prev
            ? (new Date(msg.created_at) - new Date(prev.created_at)) / 1000 / 60
            : Infinity;
          const isGrouped = !!(prev && prev.sender_id === msg.sender_id && timeDiff < 3 && !prev.deleted_at);
          return (
            <Message
              key={msg.id}
              message={msg}
              isOwn={msg.sender_id === user?.id}
              isGrouped={isGrouped}
              onContextMenu={handleContextMenu}
            />
          );
        })}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input ── */}
      <div className="message-input-wrapper">
        {chat.replyTo && (
          <div className="reply-bar">
            <div className="reply-bar-content">
              <span className="reply-bar-name">{chat.replyTo.sender_username || t("chat.you")}</span>
              <span className="reply-bar-text">{chat.replyTo.content || chat.replyTo.encrypted_content || "…"}</span>
            </div>
            <button className="reply-bar-close" onClick={() => chat.setReplyTo(null)}>×</button>
          </div>
        )}
        {attachmentPreviews.length > 0 && (
          <div className="attachment-previews">
            {attachmentPreviews.map((a, i) => (
              <div key={a.id} className="attachment-preview-item">
                <img src={a.url} alt="" className="attachment-preview-thumb" />
                <button className="attachment-preview-remove" onClick={() => removeAttachment(i)}>×</button>
              </div>
            ))}
          </div>
        )}
        <div className="message-input-bar">
          <button className="attach-btn" onClick={() => fileInputRef.current?.click()} title={t("chat.attach")}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/>
            </svg>
          </button>
          <input type="file" ref={fileInputRef} style={{ display: "none" }} accept="image/*" multiple onChange={handleFileSelect} />
          <textarea
            ref={textareaRef}
            className="msg-textarea"
            placeholder={t("chat.type_message")}
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className="send-btn"
            onClick={sendMessage}
            disabled={!text.trim() && attachmentPreviews.length === 0}
            title={t("chat.send")}
          >
            <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor">
              <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
            </svg>
          </button>
        </div>
      </div>

      {/* ── Overlays ── */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          isOwn={contextMenu.message?.sender_id === user?.id}
          isFailed={contextMenu.message?.status === "failed"}
          onClose={() => setContextMenu(null)}
          onEdit={handleEdit}
          onDelete={contextMenu.message?.status === "failed" ? handleDeleteFailed : handleDelete}
          onReply={handleReply}
          onForward={handleForward}
          onRetryFailed={handleRetryFailed}
          onReact={emoji => {
            if (contextMenu.message?.status === "failed") return;
            apiFetch(`/api/v1/messages/${contextMenu.message.id}/reactions`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ emoji }),
            }).then(() => loadMessages()).catch(() => {});
          }}
        />
      )}
      {editTarget && (
        <EditModal
          initialContent={editTarget.content || ""}
          onSave={handleEditSave}
          onCancel={() => setEditTarget(null)}
        />
      )}
      {forwardTarget && (
        <ForwardModal message={forwardTarget} onClose={() => setForwardTarget(null)} />
      )}
      {deleteTarget && (
        <DeleteConfirmModal onConfirm={handleDeleteConfirm} onCancel={() => setDeleteTarget(null)} />
      )}
    </div>
  );
}

function formatLastSeen(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const diff = (Date.now() - d) / 1000;
  if (diff < 60)    return "last seen just now";
  if (diff < 3600)  return `last seen ${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `last seen ${Math.floor(diff / 3600)}h ago`;
  return `last seen ${d.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

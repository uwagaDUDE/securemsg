import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { apiFetch, parseError } from "../../utils/api";
import { avatarBg } from "../../utils/helpers";
import CreateModal from "../modals/CreateModal";

export default function Sidebar({ activeTab, setActiveTab, onSelectChat, onSelectChannel, onSelectGroup }) {
  const { t } = useTranslation();
  const [createModal, setCreateModal] = useState(null);
  const [showJoin, setShowJoin] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [joinError, setJoinError] = useState("");
  const [joinLoading, setJoinLoading] = useState(false);
  const [search, setSearch] = useState("");
  const { user, logout } = useAuth();
  const { users, channels, setChannels, groups, setGroups, activeChatId, activeChannelId, activeGroupId, unreadCounts } = useChat();

  const filteredUsers = users
    .filter(u => u.id !== user?.id)
    .filter(u => !search || u.username.toLowerCase().includes(search.toLowerCase()));

  const filteredChannels = channels.filter(ch =>
    !search || ch.name.toLowerCase().includes(search.toLowerCase())
  );

  const filteredGroups = groups.filter(g =>
    !search || g.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="sidebar">
      {/* ── Header ── */}
      <div className="sidebar-header">
        <div className="s-avatar" style={{ background: avatarBg(user?.username || '') }}>
          {user?.username?.charAt(0).toUpperCase()}
        </div>
        <span className="s-name">{user?.username}</span>
        <div className="s-actions">
          <button className="icon-btn" onClick={logout} title={t("auth.logout")}>
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
              <polyline points="16 17 21 12 16 7"/>
              <line x1="21" y1="12" x2="9" y2="12"/>
            </svg>
          </button>
        </div>
      </div>

      {/* ── Search ── */}
      <div className="sidebar-search">
        <div className="search-wrap">
          <input
            type="text"
            placeholder={t("chat.search_users")}
            className="search-input"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {/* ── Tabs ── */}
      <div className="sidebar-tabs">
        <button className={`tab-btn ${activeTab === "contacts" ? "active" : ""}`} onClick={() => setActiveTab("contacts")}>
          {t("chat.contacts")}
        </button>
        <button className={`tab-btn ${activeTab === "channels" ? "active" : ""}`} onClick={() => setActiveTab("channels")}>
          {t("chat.channels")}
        </button>
        <button className={`tab-btn ${activeTab === "groups" ? "active" : ""}`} onClick={() => setActiveTab("groups")}>
          {t("chat.groups")}
        </button>
      </div>

      {/* ── Contacts ── */}
      <div className={`tab-content ${activeTab !== "contacts" ? "hidden" : ""}`}>
        {filteredUsers.length === 0 && (
          <div style={{ padding: "32px 16px", textAlign: "center", color: "var(--text-3)", fontSize: 13 }}>
            {search ? t("chat.no_results") : t("chat.no_contacts")}
          </div>
        )}
        {filteredUsers.map(u => (
          <div
            key={u.id}
            className={`chat-row ${activeChatId === u.id ? "active" : ""}`}
            onClick={() => onSelectChat(u)}
          >
            <div className="chat-row-ava" style={{ background: avatarBg(u.username) }}>
              {u.username.charAt(0).toUpperCase()}
              {u.is_online && <span className="ava-dot" />}
            </div>
            <div className="chat-row-body">
              <div className="chat-row-head">
                <span className="chat-row-name">{u.username}</span>
              </div>
              <div className="chat-row-foot">
                <span className={`chat-row-hint ${u.is_online ? "online" : ""}`}>
                  {u.is_online ? t("chat.online") : (u.last_seen ? formatLastSeen(u.last_seen) : "")}
                </span>
                {unreadCounts[u.id] > 0 && (
                  <span className="chat-row-badge">{unreadCounts[u.id] > 99 ? "99+" : unreadCounts[u.id]}</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* ── Channels ── */}
      <div className={`tab-content ${activeTab !== "channels" ? "hidden" : ""}`}>
        <button className="create-btn" onClick={() => setCreateModal("channel")}>
          + {t("chat.new_channel")}
        </button>
        {filteredChannels.map(ch => (
          <div
            key={ch.id}
            className={`chat-row ${activeChannelId === ch.id ? "active" : ""}`}
            onClick={() => onSelectChannel(ch)}
          >
            <div className="chat-row-ava ch-ava" style={{ background: avatarBg(ch.name) }}>
              #
            </div>
            <div className="chat-row-body">
              <div className="chat-row-head">
                <span className="chat-row-name">{ch.name}</span>
              </div>
              <div className="chat-row-foot">
                <span className="chat-row-hint">{t("chat.channel")}</span>
              </div>
            </div>
          </div>
        ))}
        <button className="join-code-btn" onClick={() => { setShowJoin(true); setJoinError(""); }}>
          🔗 {t("chat.join_by_code")}
        </button>
      </div>

      {/* ── Groups ── */}
      <div className={`tab-content ${activeTab !== "groups" ? "hidden" : ""}`}>
        <button className="create-btn" onClick={() => setCreateModal("group")}>
          + {t("chat.new_group")}
        </button>
        {filteredGroups.map(g => (
          <div
            key={g.id}
            className={`chat-row ${activeGroupId === g.id ? "active" : ""}`}
            onClick={() => onSelectGroup(g)}
          >
            <div className="chat-row-ava" style={{ background: avatarBg(g.name) }}>
              {g.name.charAt(0).toUpperCase()}
            </div>
            <div className="chat-row-body">
              <div className="chat-row-head">
                <span className="chat-row-name">{g.name}</span>
              </div>
              <div className="chat-row-foot">
                <span className="chat-row-hint">
                  {g.member_count ? `${g.member_count} ${t("chat.members")}` : t("chat.group")}
                </span>
              </div>
            </div>
          </div>
        ))}
        <button className="join-code-btn" onClick={() => { setShowJoin(true); setJoinError(""); }}>
          🔗 {t("chat.join_by_code")}
        </button>
      </div>

      {createModal && <CreateModal type={createModal} onClose={() => setCreateModal(null)} />}

      {/* ── Join by code modal ── */}
      {showJoin && (
        <div
          className="modal-overlay"
          onClick={e => { if (e.target === e.currentTarget) { setShowJoin(false); setJoinCode(""); } }}
        >
          <div className="modal-box join-modal">
            <h3>{t("chat.join_by_code")}</h3>
            <form onSubmit={async e => {
              e.preventDefault();
              if (!joinCode.trim()) return;
              setJoinLoading(true);
              setJoinError("");
              try {
                const isGroup = activeTab === "groups";
                const url = isGroup
                  ? `/api/v1/groups/join/${encodeURIComponent(joinCode.trim())}`
                  : `/api/v1/channels/join/${encodeURIComponent(joinCode.trim())}`;
                const res = await apiFetch(url, { method: "POST" });
                if (!res.ok) { setJoinError(await parseError(res)); return; }
                const item = await res.json();
                if (isGroup) { setGroups([...groups, item]); onSelectGroup(item); }
                else { setChannels([...channels, item]); onSelectChannel(item); }
                setShowJoin(false);
                setJoinCode("");
              } catch {
                setJoinError(t("chat.failed_to_join"));
              } finally {
                setJoinLoading(false);
              }
            }}>
              <input
                type="text"
                placeholder={t("chat.enter_invite_code")}
                value={joinCode}
                onChange={e => setJoinCode(e.target.value)}
                autoFocus
              />
              {joinError && <div className="error-msg">{joinError}</div>}
              <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                <button type="submit" className="modal-btn-primary" disabled={joinLoading} style={{ flex: 1 }}>
                  {joinLoading ? t("common.loading") : t("chat.join")}
                </button>
                <button type="button" className="btn-cancel" onClick={() => { setShowJoin(false); setJoinCode(""); }} style={{ flex: 1 }}>
                  {t("chat.cancel")}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

function formatLastSeen(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

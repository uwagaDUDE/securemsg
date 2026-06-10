import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { escHtml } from "../../utils/helpers";
import { getToken } from "../../utils/api";

function AttachmentImage({ att }) {
  const [src, setSrc] = useState(null);

  useEffect(() => {
    let cancelled = false;
    const token = getToken();
    fetch(`/api/v1/attachments/${att.id}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => { if (!r.ok) throw new Error(); return r.blob(); })
      .then(blob => { if (!cancelled) setSrc(URL.createObjectURL(blob)); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [att.id]);

  if (!src) return <div className="message-image"><div className="img-loading">Loading…</div></div>;
  return (
    <div className="message-image">
      <img src={src} alt="" onClick={() => window.open(src, "_blank")} />
    </div>
  );
}

export default function Message({ message, isOwn, isGrouped, onContextMenu }) {
  const { t } = useTranslation();
  const isDeleted = !!message.deleted_at;
  const isFailed = message.status === "failed";

  return (
    <div
      className={[
        "message",
        isOwn ? "own" : "other",
        isGrouped ? "grouped" : "",
        isDeleted ? "deleted" : "",
        isFailed ? "failed" : "",
      ].filter(Boolean).join(" ")}
      data-msg-id={message.id}
      onContextMenu={e => { e.preventDefault(); onContextMenu?.(e, message); }}
    >
      {/* Sender name — only in group/channel, only on first in sequence */}
      {!isOwn && !isGrouped && message.sender_username && (
        <div className="message-sender-name">
          {escHtml(message.sender_username)}
        </div>
      )}

      {/* Attachments */}
      {message.attachments?.length > 0 && (
        <div className="message-attachments">
          {message.attachments.map(a => (
            <AttachmentImage key={a.id} att={a} />
          ))}
        </div>
      )}

      {/* Bubble */}
      {(message.content || message.encrypted_content || message.attachments?.length === 0) && (
        <div className="message-text">
          <span className="message-body">
            {isDeleted
              ? t("chat.deleted")
              : escHtml(message.content || message.encrypted_content || t("chat.encrypted"))}
          </span>
          <span className="message-meta">
            {message.edited_at && !isDeleted && (
              <span className="meta-edited">{t("chat.edited")}</span>
            )}
            <span className="message-time">
              {message.created_at
                ? new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : ""}
            </span>
            {isOwn && !isFailed && (
              <span className={`meta-check ${message.is_read ? "read" : ""}`}>✓✓</span>
            )}
          </span>
        </div>
      )}

      {/* Image-only: just meta */}
      {!message.content && !message.encrypted_content && message.attachments?.length > 0 && (
        <div className="message-text" style={{ minWidth: 64 }}>
          <span className="message-meta">
            <span className="message-time">
              {message.created_at
                ? new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
                : ""}
            </span>
            {isOwn && !isFailed && (
              <span className={`meta-check ${message.is_read ? "read" : ""}`}>✓✓</span>
            )}
          </span>
        </div>
      )}

      {/* Reactions */}
      {message.reactions?.length > 0 && (
        <div className="message-reactions">
          {message.reactions.map((r, i) => (
            <span key={i} className="message-reaction-badge">
              {r.emoji}{r.count > 1 ? <span style={{ fontSize: 10, marginLeft: 2, opacity: 0.7 }}>{r.count}</span> : null}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

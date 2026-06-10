import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";
import { useChat } from "../../context/ChatContext";
import { apiFetch } from "../../utils/api";
import { encryptMessage } from "../../utils/crypto";

export default function ForwardModal({ message, onClose }) {
  const { t } = useTranslation();
  const { user, myBroadcastKey } = useAuth();
  const chat = useChat();
  const [sending, setSending] = useState(false);

  const contacts = chat.users.filter((u) => u.id !== user?.id);
  const groups = chat.groups;

  const forwarding = useRef(false);

  async function handleForward(targetType, targetId) {
    if (forwarding.current) return;
    forwarding.current = true;
    setSending(true);
    try {
      const content = message.content || message.encrypted_content || "";
      const isEncrypted = targetType === "user" || targetType === "group";
      let encryptedContent = content;
      if (isEncrypted && myBroadcastKey) {
        encryptedContent = await encryptMessage(content, myBroadcastKey);
      }
      if (targetType === "user") {
        await apiFetch("/api/v1/messages/" + targetId + "/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypted_content: encryptedContent, attachment_ids: [] }),
        });
      } else if (targetType === "group") {
        await apiFetch("/api/v1/groups/" + targetId + "/send", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ encrypted_content: encryptedContent, attachment_ids: [] }),
        });
      }
      onClose();
    } catch (_) {
      setSending(false);
      forwarding.current = false;
    }
  }

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-box" style={{ maxWidth: 360 }}>
        <h3>{t("chat.forward_message")}</h3>
        {sending ? (
          <p>{t("chat.sending")}...</p>
        ) : (
          <>
            {contacts.length > 0 && (
              <>
                <p style={{ fontSize: 12, color: "var(--text-mute)", marginBottom: 6 }}>{t("chat.contacts")}</p>
                <div style={{ maxHeight: 160, overflowY: "auto", marginBottom: 10 }}>
                  {contacts.map((u) => (
                    <div key={u.id} className="contact-item" style={{ padding: "6px 8px", cursor: "pointer" }}
                      onClick={() => handleForward("user", u.id)}>
                      <span className="contact-name">{u.username}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {groups.length > 0 && (
              <>
                <p style={{ fontSize: 12, color: "var(--text-mute)", marginBottom: 6 }}>{t("chat.groups")}</p>
                <div style={{ maxHeight: 160, overflowY: "auto", marginBottom: 10 }}>
                  {groups.map((g) => (
                    <div key={g.id} className="contact-item" style={{ padding: "6px 8px", cursor: "pointer" }}
                      onClick={() => handleForward("group", g.id)}>
                      <span className="contact-name">{g.name}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {contacts.length === 0 && groups.length === 0 && (
              <p style={{ color: "var(--text-mute)" }}>{t("chat.no_contacts")}</p>
            )}
            <button className="btn-cancel" onClick={onClose} style={{ width: "100%", marginTop: 8 }}>
              {t("chat.cancel")}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

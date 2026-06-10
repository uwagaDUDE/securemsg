import { useState } from "react";
import { useTranslation } from "react-i18next";
import { apiFetch, parseError } from "../../utils/api";
import { useChat } from "../../context/ChatContext";

export default function CreateModal({ type, onClose }) {
  const { t } = useTranslation();
  const chat = useChat();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const title = type === "channel" ? t("chat.new_channel") : t("chat.new_group");
  const apiUrl = type === "channel" ? "/api/v1/channels" : "/api/v1/groups";

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    if (!name.trim()) {
      setError(t("chat.name_required"));
      return;
    }
    setLoading(true);
    try {
      const body = type === "channel" ? { name: name.trim(), description: description.trim() || null } : { name: name.trim() };
      const res = await apiFetch(apiUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        setError(await parseError(res));
        return;
      }
      const item = await res.json();
      if (type === "channel") {
        chat.setChannels([...chat.channels, item]);
      } else {
        chat.setGroups([...chat.groups, item]);
      }
      onClose();
    } catch {
      setError(t("chat.failed_to_create"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-box">
        <h3>{title}</h3>
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder={t("chat.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          {type === "channel" && (
            <input
              type="text"
              placeholder={t("chat.description_optional")}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          )}
          {error && <div className="error-msg">{error}</div>}
          <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
            <button type="submit" disabled={loading} style={{ flex: 1 }}>
              {loading ? t("chat.creating") : t("chat.create")}
            </button>
            <button type="button" className="btn-cancel" onClick={onClose} style={{ flex: 1 }}>
              {t("chat.cancel")}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

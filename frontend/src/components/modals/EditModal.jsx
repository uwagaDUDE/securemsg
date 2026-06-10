import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function EditModal({ initialContent, onSave, onCancel }) {
  const { t } = useTranslation();
  const [text, setText] = useState(initialContent || "");

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-box">
        <h3>{t("chat.edit_message")}</h3>
        <textarea
          className="edit-textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoFocus
          rows={4}
        />
        <div className="delete-modal-actions" style={{ marginTop: 12 }}>
          <button className="btn-danger" onClick={() => onSave(text.trim())} disabled={!text.trim()}>
            {t("chat.save")}
          </button>
          <button className="btn-cancel" onClick={onCancel}>
            {t("chat.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

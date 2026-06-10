import { useRef } from "react";
import { useTranslation } from "react-i18next";

export default function DeleteConfirmModal({ onConfirm, onCancel }) {
  const { t } = useTranslation();
  const cbRef = useRef(null);

  return (
    <div className="modal-overlay" onClick={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="modal-box delete-modal">
        <span className="delete-modal-icon">🗑️</span>
        <h3>{t("chat.delete_message")}</h3>
        <p className="delete-modal-desc">{t("chat.delete_confirm_desc")}</p>
        <label className="delete-modal-toggle">
          <input type="checkbox" ref={cbRef} />
          <span className="toggle-track" />
          <span>{t("chat.delete_for_all")}</span>
        </label>
        <div className="delete-modal-actions">
          <button className="btn-danger" onClick={() => onConfirm(cbRef.current?.checked)}>{t("chat.delete")}</button>
          <button className="btn-cancel" onClick={onCancel}>{t("chat.cancel")}</button>
        </div>
      </div>
    </div>
  );
}

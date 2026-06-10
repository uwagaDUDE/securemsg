import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const EMOJIS = ["👍", "❤️", "😂", "😮", "😢", "😡"];
const GAP = 8;

export default function ContextMenu({ x, y, isOwn, isFailed, onClose, onEdit, onDelete, onReply, onForward, onRetryFailed, onReact }) {
  const { t } = useTranslation();
  const menuRef = useRef(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  // Start at (0,0) so the element is fully in-viewport when measured.
  // getBoundingClientRect clips elements that overflow the viewport,
  // so measuring at the click position gives wrong dimensions near edges.
  const [pos, setPos] = useState({ left: 0, top: 0, visible: false });

  useEffect(() => {
    const el = menuRef.current;
    if (!el) return;
    const { width, height } = el.getBoundingClientRect();
    const w = window.innerWidth;
    const h = window.innerHeight;
    const left = x + width + GAP <= w ? x : x - width;
    const top  = y + height + GAP <= h ? y : y - height;
    setPos({
      left: Math.max(GAP, left),
      top:  Math.max(GAP, top),
      visible: true,
    });
  }, [x, y]);

  useEffect(() => {
    function handleClick(e) {
      if (!e.target.closest("#context-menu")) onCloseRef.current();
    }
    document.addEventListener("click", handleClick);
    return () => document.removeEventListener("click", handleClick);
  }, []);

  const style = {
    position: "fixed",
    left: pos.left,
    top: pos.top,
    visibility: pos.visible ? "visible" : "hidden",
  };

  if (isFailed) {
    return (
      <div id="context-menu" className="context-menu" style={style} ref={menuRef}>
        <div className="context-menu-item" onClick={() => { onRetryFailed(); onClose(); }}>{t("context_menu.retry")}</div>
        <div className="context-menu-item" onClick={() => { onDelete(); onClose(); }}>{t("context_menu.delete")}</div>
      </div>
    );
  }

  return (
    <div id="context-menu" className="context-menu" style={style} ref={menuRef}>
      {isOwn && (
        <>
          <div className="context-menu-item" onClick={() => { onEdit(); onClose(); }}>{t("context_menu.edit")}</div>
          <div className="context-menu-item" onClick={() => { onDelete(); onClose(); }}>{t("context_menu.delete")}</div>
          <div className="context-menu-separator" />
        </>
      )}
      <div className="context-menu-item" onClick={() => { onReply(); onClose(); }}>{t("context_menu.reply")}</div>
      <div className="context-menu-item" onClick={() => { onForward(); onClose(); }}>{t("context_menu.forward")}</div>
      <div className="context-menu-separator" />
      <div className="context-menu-reactions">
        {EMOJIS.map((emoji) => (
          <span key={emoji} className="ctx-react" onClick={() => { onReact(emoji); onClose(); }}>
            {emoji}
          </span>
        ))}
      </div>
    </div>
  );
}

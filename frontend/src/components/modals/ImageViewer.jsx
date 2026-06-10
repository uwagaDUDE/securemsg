export default function ImageViewer({ src, onClose }) {
  return (
    <div className="modal-overlay image-viewer" onClick={onClose}>
      <img src={src} className="image-viewer-img" alt="" />
    </div>
  );
}

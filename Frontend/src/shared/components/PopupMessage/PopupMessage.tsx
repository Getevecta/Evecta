import React, { useEffect } from "react";
import { createPortal } from "react-dom";
import { Slack, X } from "lucide-react";
import "./PopupMessage.css";

type PopupType = 'success' | 'error' | 'info';

interface PopupMessageProps {
  message: string;
  type?: PopupType;
  isVisible: boolean;
  onClose: () => void;
  autoHideMs?: number;
}

const PopupMessage: React.FC<PopupMessageProps> = ({
  message,
  isVisible,
  onClose,
  autoHideMs = 3500,
}) => {
  useEffect(() => {
    if (!isVisible) return;
    const timer = setTimeout(onClose, autoHideMs);
    return () => clearTimeout(timer);
  }, [isVisible, autoHideMs, onClose]);

  if (!isVisible || !message) return null;

  const content = (
    <div
      className="popup-message popup-message-lead-gen-style"
      role="status"
      aria-live="polite"
    >
      <div className="popup-message-inner">
        <Slack size={18} className="popup-message-icon" aria-hidden />
        <span className="popup-message-text">{message}</span>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close message"
          className="popup-message-close"
        >
          <X size={18} />
        </button>
      </div>
    </div>
  );

  const target = typeof document !== 'undefined' ? document.body : null;
  return target ? createPortal(content, target) : content;
};

export default PopupMessage;

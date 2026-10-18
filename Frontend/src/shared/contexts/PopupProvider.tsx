import React, { createContext, useCallback, useContext, useState } from "react";
import { toast } from "sonner";

type PopupType = 'success' | 'error' | 'info';

interface PopupState {
  isVisible: boolean;
  message: string;
  type: PopupType;
}

interface PopupContextValue {
  popupState: PopupState;
  showPopup: (message: string, type?: PopupType, autoHideMs?: number) => void;
  hidePopup: () => void;
}

const PopupContext = createContext<PopupContextValue | undefined>(undefined);

export const usePopup = (): PopupContextValue => {
  const ctx = useContext(PopupContext);
  if (!ctx) throw new Error("usePopup must be used within PopupProvider");
  return ctx;
};

export const PopupProvider: React.FC<React.PropsWithChildren<{}>> = ({ children }) => {
  const [popupState, setPopupState] = useState<PopupState>({
    isVisible: false,
    message: "",
    type: 'info',
  });
  const [autoHideMs, setAutoHideMs] = useState<number>(5000);

  const showPopup = useCallback((message: string | any, type: PopupType = 'info', hideAfterMs: number = 5000) => {
    setAutoHideMs(hideAfterMs);

    // Normalize message into a string
    let messageString: string;
    if (typeof message === 'object' && message !== null) {
      messageString = message?.message || message?.detail || message?.error || JSON.stringify(message);
    } else if (typeof message === 'string') {
      messageString = message;
    } else {
      messageString = String(message);
    }

    const trimmed = messageString.trim();

    // Update local state so screens like OTP can react to error state,
    // but delegate the visual notification to the global Sonner toaster.
    setPopupState({ isVisible: true, message: trimmed, type });
    if (type === "success") {
      toast.success(trimmed, { duration: 4500 });
    } else if (type === "error") {
      toast.error(trimmed, { duration: 5000 });
    } else {
      toast(trimmed, { duration: 4000 });
    }

    if (hideAfterMs > 0) {
      window.setTimeout(() => {
        setPopupState(prev => ({ ...prev, isVisible: false }));
      }, hideAfterMs);
    }
  }, []);

  const hidePopup = useCallback(() => {
    setPopupState(prev => ({ ...prev, isVisible: false }));
  }, []);

  return (
    <PopupContext.Provider value={{ popupState, showPopup, hidePopup }}>
      {children}
    </PopupContext.Provider>
  );
};



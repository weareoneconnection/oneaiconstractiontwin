"use client";
import { createContext, useCallback, useContext, useMemo, useState } from "react";

const ToastContext = createContext({ notify: () => {} });

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback(id => setToasts(list => list.filter(item => item.id !== id)), []);

  const notify = useCallback((message, tone = "info", timeout = 6000) => {
    const id = `${Date.now()}-${Math.random()}`;
    setToasts(list => [...list, { id, message, tone }]);
    if (timeout) setTimeout(() => dismiss(id), timeout);
    return id;
  }, [dismiss]);

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map(toast => (
          <div key={toast.id} className={`toast ${toast.tone}`} onClick={() => dismiss(toast.id)}>
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

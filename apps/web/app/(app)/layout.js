import AuthGate from "../../components/AuthGate";
import AppShell from "../../components/shell/AppShell";
import { SessionProvider } from "../../lib/session";
import { ToastProvider } from "../../components/ui/Toast";

export default function AppLayout({ children }) {
  return (
    <AuthGate>
      <SessionProvider>
        <ToastProvider>
          <AppShell>{children}</AppShell>
        </ToastProvider>
      </SessionProvider>
    </AuthGate>
  );
}

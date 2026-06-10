import { useState } from "react";
import { useTranslation } from "react-i18next";
import { QueryProvider } from "./context/QueryProvider";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { SocketProvider } from "./context/SocketContext";
import { ChatProvider } from "./context/ChatContext";
import LoginPage from "./components/pages/LoginPage";
import RegisterPage from "./components/pages/RegisterPage";
import MainPage from "./components/pages/MainPage";

function AppContent() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
  const [page, setPage] = useState("login");
  const [prefillUsername, setPrefillUsername] = useState("");

  if (loading) {
    return <div className="loading-screen">{t("common.loading")}</div>;
  }

  if (user) {
    return (
      <ChatProvider>
        <SocketProvider>
          <MainPage />
        </SocketProvider>
      </ChatProvider>
    );
  }

  if (page === "register") {
    return (
      <RegisterPage
        onSwitchToLogin={(username) => {
          setPrefillUsername(username || "");
          setPage("login");
        }}
      />
    );
  }

  return (
    <LoginPage
      prefillUsername={prefillUsername}
      onSwitchToRegister={() => { setPrefillUsername(""); setPage("register"); }}
    />
  );
}

export default function App() {
  return (
    <QueryProvider>
      <AuthProvider>
        <AppContent />
      </AuthProvider>
    </QueryProvider>
  );
}

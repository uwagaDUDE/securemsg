import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";

export default function LoginPage({ onSwitchToRegister, prefillUsername = "" }) {
  const { t, i18n } = useTranslation();
  const { login, cryptoError } = useAuth();
  const [username, setUsername] = useState(prefillUsername);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (cryptoError) { setError(cryptoError); return; }
    if (!username || !password) { setError(t("auth.fill_all_fields")); return; }

    setLoading(true);
    try {
      await login(username, password);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  return (
    <div id="login-page" className="auth-page">
      <div className="lang-switcher">
        <button onClick={() => i18n.changeLanguage("en")} className={i18n.language?.startsWith("en") ? "active" : ""}>EN</button>
        <button onClick={() => i18n.changeLanguage("ru")} className={i18n.language?.startsWith("ru") ? "active" : ""}>RU</button>
      </div>
      <img className="auth-logo" src="/favicon.png" alt="Secure Messenger" />
      <h2>Secure Messenger</h2>
      <form onSubmit={handleSubmit}>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          type="text" placeholder={t("auth.username")} autoComplete="off"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password" placeholder={t("auth.password")}
        />
        <button type="submit" disabled={loading}>{t("auth.login")}</button>
        {error && <p className="error-msg">{error}</p>}
      </form>
      <div className="switch">
        {t("auth.no_account")} <a onClick={onSwitchToRegister}>{t("auth.create_one")}</a>
      </div>
    </div>
  );
}

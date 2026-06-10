import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useAuth } from "../../context/AuthContext";
import { generateKeys } from "../../utils/crypto";

export default function RegisterPage({ onSwitchToLogin }) {
  const { t } = useTranslation();
  const { register, cryptoError } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");

    if (cryptoError) { setError(cryptoError); return; }
    if (!username || !password) { setError(t("auth.fill_all_fields")); return; }
    if (username.length < 3 || username.length > 32 || !/^[a-zA-Z0-9_]+$/.test(username)) {
      setError(t("auth.username_invalid"));
      return;
    }
    if (password.length < 8) {
      setError(t("auth.password_too_short"));
      return;
    }

    setLoading(true);
    try {
      const keys = await generateKeys(password);
      await register(username, password, keys);
      onSwitchToLogin(username);
    } catch (err) {
      setError(err.message);
      setLoading(false);
    }
  }

  return (
    <div id="register-page" className="auth-page">
      <img className="auth-logo" src="/favicon.png" alt="Secure Messenger" />
      <h2>{t("auth.create_account")}</h2>
      <form onSubmit={handleSubmit}>
        <input
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          type="text" placeholder={t("auth.choose_username")} autoComplete="off"
        />
        <input
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          type="password" placeholder={t("auth.choose_password")}
        />
        <button type="submit" disabled={loading}>
          {loading ? t("auth.generating_keys") : t("auth.register")}
        </button>
        {error && <p className="error-msg">{error}</p>}
      </form>
      <div className="switch">
        {t("auth.has_account")} <a onClick={() => onSwitchToLogin()}>{t("auth.sign_in")}</a>
      </div>
    </div>
  );
}

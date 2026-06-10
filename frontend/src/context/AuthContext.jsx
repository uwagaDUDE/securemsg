import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { apiFetch, setTokens, getToken, getUserId, getUsername, clearAuth } from "../utils/api";
import { decryptPrivateKey, importBroadcastKey, getCryptoErrorMessage } from "../utils/crypto";
import { b64dec, b64enc } from "../utils/helpers";

const AuthContext = createContext(null);

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [privateKey, setPrivateKey] = useState(null);
  const [myBroadcastKey, setMyBroadcastKey] = useState(null);
  const [storedPassword, setStoredPassword] = useState(null);
  const [cryptoError, setCryptoError] = useState(getCryptoErrorMessage());

  const initApp = useCallback(async (token) => {
    const res = await apiFetch("/api/v1/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    });
    const currentUser = await res.json();
    setUser(currentUser);

    const pass = storedPassword || sessionStorage.getItem("password");
    if (pass && currentUser.encrypted_private_key) {
      try {
        const encBlob = b64dec(currentUser.encrypted_private_key);
        const key = await decryptPrivateKey(encBlob, pass);
        setPrivateKey(key);
      } catch (e) {
        console.error("[Auth] decrypt private key failed:", e);
      }
    }
    if (currentUser.broadcast_key) {
      const bk = await importBroadcastKey(b64dec(currentUser.broadcast_key));
      setMyBroadcastKey(bk);
    }
    return currentUser;
  }, [storedPassword]);

  useEffect(() => {
    const token = getToken();
    if (token) {
      initApp(token).then(() => setLoading(false)).catch(() => {
        clearAuth();
        setLoading(false);
      });
    } else {
      setLoading(false);
    }
  }, [initApp]);

  const login = useCallback(async (username, password) => {
    const res = await fetch("/api/v1/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Login failed");
    }
    const data = await res.json();
    setTokens(data.access_token, data.refresh_token);
    localStorage.setItem("user_id", data.user_id);
    localStorage.setItem("username", data.username);
    sessionStorage.setItem("password", password);
    setStoredPassword(password);
    await initApp(data.access_token);
  }, [initApp]);

  const register = useCallback(async (username, password, keys) => {
    const res = await fetch("/api/v1/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        password,
        public_key: b64enc(keys.publicKey),
        encrypted_private_key: b64enc(keys.encryptedPrivateKey),
        broadcast_key: b64enc(keys.broadcastKey),
      }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Registration failed");
    }
  }, []);

  const logout = useCallback(async () => {
    const rt = localStorage.getItem("refresh_token");
    if (rt) {
      try {
        await apiFetch("/api/v1/auth/logout", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: rt }),
        });
      } catch {}
    }
    clearAuth();
    sessionStorage.removeItem("password");
    setUser(null);
    setPrivateKey(null);
    setMyBroadcastKey(null);
    setStoredPassword(null);
    window.location.reload();
  }, []);

  const value = {
    user, loading, privateKey, myBroadcastKey, cryptoError,
    login, register, logout, initApp,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

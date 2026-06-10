let refreshLock = null;
let appToken = null;

export function getToken() {
  return localStorage.getItem("token");
}

export function getRefreshToken() {
  return localStorage.getItem("refresh_token");
}

export function setTokens(accessToken, refreshToken) {
  localStorage.setItem("token", accessToken);
  if (refreshToken) localStorage.setItem("refresh_token", refreshToken);
  appToken = accessToken;
}

export function clearAuth() {
  localStorage.removeItem("token");
  localStorage.removeItem("refresh_token");
  localStorage.removeItem("user_id");
  localStorage.removeItem("username");
  appToken = null;
}

export function getUserId() {
  return localStorage.getItem("user_id");
}

export function getUsername() {
  return localStorage.getItem("username");
}

export async function refreshToken() {
  if (refreshLock) return refreshLock;
  const rt = getRefreshToken();
  if (!rt) return null;

  refreshLock = (async () => {
    try {
      const res = await fetch("/api/v1/auth/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: rt }),
      });
      if (!res.ok) return null;
      const data = await res.json();
      setTokens(data.access_token, data.refresh_token);
      localStorage.setItem("user_id", data.user_id);
      return data.access_token;
    } catch {
      return null;
    } finally {
      refreshLock = null;
    }
  })();
  return refreshLock;
}

export async function uploadAttachment(file) {
  const token = appToken || getToken();
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/v1/attachments", {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  });
  if (!res.ok) {
    const err = await parseError(res).catch(() => "Upload failed");
    throw new Error(err);
  }
  return res.json();
}

export async function apiFetch(url, options = {}) {
  options.headers = options.headers || {};
  if (!options.headers["Authorization"]) {
    options.headers["Authorization"] = "Bearer " + (appToken || getToken());
  }

  let res = await fetch(url, options);

  if (res.status === 401 || res.status === 403) {
    const newToken = await refreshToken();
    if (newToken) {
      options.headers["Authorization"] = "Bearer " + newToken;
      res = await fetch(url, options);
      if (res.status !== 401 && res.status !== 403) return res;
    }
    clearAuth();
    window.location.reload();
    throw new Error("Session expired");
  }

  return res;
}

export async function parseError(res) {
  try {
    const json = await res.json();
    if (Array.isArray(json.detail)) {
      return json.detail.map((e) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : "";
        return field ? `${field}: ${e.msg}` : e.msg;
      }).join("; ");
    }
    return json.detail || json.message || `Error ${res.status}`;
  } catch {
    const text = await res.text();
    return text || `Error ${res.status}`;
  }
}

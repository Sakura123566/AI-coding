const API_BASE = (import.meta.env.VITE_API_BASE_URL || "").replace(/\/$/, "");
const TOKEN_KEY = "research-navigator-token";

export class ApiError extends Error {
  constructor(message, { status = 0, body = null, requestId = "" } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.requestId = requestId;
    this.code = body?.error_code || `HTTP_${status}`;
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export async function api(path, { method = "GET", body, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (auth && token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError("无法连接后端，请检查公网 API 地址或本机服务是否启动。");
  }

  const requestId = response.headers.get("X-Request-ID") || "";
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    throw new ApiError("后端返回内容无法解析。", {
      status: response.status,
      requestId,
    });
  }

  if (!response.ok || payload?.status === "error") {
    throw new ApiError(payload?.message || `请求失败（HTTP ${response.status}）`, {
      status: response.status,
      body: payload,
      requestId,
    });
  }
  return payload;
}

export const API = {
  health: () => api("/api/health", { auth: false }),
  research: (keyword, limit = 10) =>
    api("/api/research/run", { method: "POST", body: { keyword, limit }, auth: false }),
  register: (payload) =>
    api("/api/auth/register", { method: "POST", body: payload, auth: false }),
  login: (payload) =>
    api("/api/auth/login", { method: "POST", body: payload, auth: false }),
  me: () => api("/api/auth/me"),
  logout: () => api("/api/auth/logout", { method: "POST" }),
  sessions: () => api("/api/chat/sessions?limit=100"),
  createSession: (title = "新对话") =>
    api("/api/chat/sessions", { method: "POST", body: { title } }),
  deleteSession: (id) => api(`/api/chat/sessions/${id}`, { method: "DELETE" }),
  messages: (id) => api(`/api/chat/sessions/${id}/messages?limit=500`),
  chat: (sessionId, content) =>
    api("/api/chat/message", {
      method: "POST",
      body: { session_id: sessionId, content },
    }),
  closeSession: (id) => api(`/api/chat/sessions/${id}/close`, { method: "POST" }),
  memories: () => api("/api/memory?limit=500"),
  addMemory: (content, memType = "profile_fact") =>
    api("/api/memory", { method: "POST", body: { content, mem_type: memType } }),
  deleteMemory: (id) => api(`/api/memory/${id}`, { method: "DELETE" }),
  clearMemories: () => api("/api/memory/clear", { method: "POST" }),
  profile: () => api("/api/profile"),
  searches: () => api("/api/profile/searches?limit=100"),
  kgKeywords: () => api("/api/kg/keywords"),
  kgCooccurrence: (userId) => api(`/api/kg/cooccurrence?user_id=${encodeURIComponent(userId)}`),
};
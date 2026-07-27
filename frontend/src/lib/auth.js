const TOKEN_KEY = 'amnesia_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseError(res, fallback) {
  try {
    const data = await res.json();
    return data.detail || fallback;
  } catch {
    return fallback;
  }
}

export async function signup(email, password) {
  const res = await fetch('/api/auth/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res, 'Signup failed'));
  return res.json();
}

export async function login(email, password) {
  const res = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseError(res, 'Login failed'));
  return res.json();
}

export async function getMe() {
  const res = await fetch('/api/auth/me', { headers: { ...authHeaders() } });
  if (!res.ok) throw new Error(await parseError(res, 'Not authenticated'));
  return res.json();
}

export async function regenerateApiKey() {
  const res = await fetch('/api/auth/api-key/regenerate', {
    method: 'POST',
    headers: { ...authHeaders() },
  });
  if (!res.ok) throw new Error(await parseError(res, 'Failed to regenerate API key'));
  return res.json();
}

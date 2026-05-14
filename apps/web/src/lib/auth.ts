/** Auth-specific API client (standalone fetch, no token injection loop). */

const BASE_URL = '/api/v1/auth';

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string;
  is_active: boolean;
  created_at: string;
}

async function handleResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `HTTP ${response.status}: ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // ignore
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

export const authApi = {
  async register(email: string, password: string, displayName: string): Promise<User> {
    const res = await fetch(`${BASE_URL}/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, display_name: displayName }),
    });
    return handleResponse<User>(res);
  },

  async login(email: string, password: string): Promise<AuthTokens> {
    const formData = new URLSearchParams();
    formData.set('username', email);
    formData.set('password', password);

    const res = await fetch(`${BASE_URL}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData.toString(),
    });
    return handleResponse<AuthTokens>(res);
  },

  async refresh(refreshToken: string): Promise<AuthTokens> {
    const res = await fetch(`${BASE_URL}/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    return handleResponse<AuthTokens>(res);
  },

  async getMe(accessToken: string): Promise<User> {
    const res = await fetch(`${BASE_URL}/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
    });
    return handleResponse<User>(res);
  },
};

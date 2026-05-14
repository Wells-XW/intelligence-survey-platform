import { create } from 'zustand';
import { authApi, type AuthTokens, type User } from '@/lib/auth';

const TOKENS_KEY = 'isp_auth_tokens';

function loadTokens(): AuthTokens | null {
  try {
    const raw = localStorage.getItem(TOKENS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function saveTokens(tokens: AuthTokens | null) {
  if (tokens) {
    localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  } else {
    localStorage.removeItem(TOKENS_KEY);
  }
}

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;

  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => void;
  setTokens: (tokens: AuthTokens) => void;
  initialize: () => Promise<void>;
  refreshAccessToken: () => Promise<string | null>;
}

export const useAuthStore = create<AuthState>((set, get) => ({
  accessToken: null,
  refreshToken: null,
  user: null,
  isAuthenticated: false,
  isLoading: true,

  setTokens: (tokens: AuthTokens) => {
    saveTokens(tokens);
    set({
      accessToken: tokens.access_token,
      refreshToken: tokens.refresh_token,
    });
  },

  login: async (email: string, password: string) => {
    const tokens = await authApi.login(email, password);
    get().setTokens(tokens);
    const user = await authApi.getMe(tokens.access_token);
    set({ user, isAuthenticated: true });
  },

  register: async (email: string, password: string, displayName: string) => {
    await authApi.register(email, password, displayName);
  },

  logout: () => {
    saveTokens(null);
    set({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
    });
  },

  refreshAccessToken: async () => {
    const currentRefresh = get().refreshToken;
    if (!currentRefresh) return null;

    try {
      const tokens = await authApi.refresh(currentRefresh);
      get().setTokens(tokens);
      return tokens.access_token;
    } catch {
      get().logout();
      return null;
    }
  },

  initialize: async () => {
    const stored = loadTokens();
    if (!stored) {
      set({ isLoading: false });
      return;
    }

    set({
      accessToken: stored.access_token,
      refreshToken: stored.refresh_token,
    });

    try {
      const user = await authApi.getMe(stored.access_token);
      set({ user, isAuthenticated: true, isLoading: false });
    } catch {
      // Access token expired — try refresh
      try {
        const tokens = await authApi.refresh(stored.refresh_token);
        get().setTokens(tokens);
        const user = await authApi.getMe(tokens.access_token);
        set({ user, isAuthenticated: true, isLoading: false });
      } catch {
        // Refresh failed — clear everything
        saveTokens(null);
        set({
          accessToken: null,
          refreshToken: null,
          isLoading: false,
        });
      }
    }
  },
}));

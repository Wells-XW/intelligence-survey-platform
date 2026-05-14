import { useAuthStore } from '@/features/auth/store';

const BASE_URL = '/api/v1';

interface ApiError {
  detail: string;
  status: number;
}

class ApiClient {
  private getAccessToken(): string | null {
    return useAuthStore.getState().accessToken;
  }

  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${BASE_URL}${path}`;
    const token = this.getAccessToken();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>),
    };

    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    let response = await fetch(url, {
      ...options,
      headers,
    });

    // Auto-refresh on 401
    if (response.status === 401 && token) {
      const newToken = await useAuthStore.getState().refreshAccessToken();
      if (newToken) {
        headers['Authorization'] = `Bearer ${newToken}`;
        response = await fetch(url, { ...options, headers });
      }
    }

    if (!response.ok) {
      const error: ApiError = {
        detail: `HTTP ${response.status}: ${response.statusText}`,
        status: response.status,
      };
      try {
        const body = await response.json();
        error.detail = body.detail || error.detail;
      } catch {
        // ignore parse error
      }
      throw error;
    }

    // 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    return response.json();
  }

  get<T>(path: string) {
    return this.request<T>(path, { method: 'GET' });
  }

  post<T>(path: string, data?: unknown) {
    return this.request<T>(path, {
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  put<T>(path: string, data: unknown) {
    return this.request<T>(path, {
      method: 'PUT',
      body: JSON.stringify(data),
    });
  }

  delete<T>(path: string) {
    return this.request<T>(path, { method: 'DELETE' });
  }
}

export const api = new ApiClient();

// Survey types (shared between frontend and backend)
export interface Survey {
  id: string;
  owner_id?: string | null;
  title: string;
  description: string | null;
  json_content: Record<string, unknown>;
  status: 'draft' | 'published' | 'closed';
  created_at: string;
  updated_at: string;
  version: number;
}

export interface SurveyListItem {
  id: string;
  title: string;
  status: 'draft' | 'published' | 'closed';
  created_at: string;
  updated_at: string;
  version: number;
}

export interface CreateSurveyRequest {
  title: string;
  description?: string;
  json_content?: Record<string, unknown>;
}

export interface UpdateSurveyRequest {
  title?: string;
  description?: string;
  json_content?: Record<string, unknown>;
  status?: string;
}

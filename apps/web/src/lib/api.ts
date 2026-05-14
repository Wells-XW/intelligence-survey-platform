const BASE_URL = '/api/v1';

interface ApiError {
  detail: string;
  status: number;
}

class ApiClient {
  private async request<T>(path: string, options?: RequestInit): Promise<T> {
    const url = `${BASE_URL}${path}`;
    const response = await fetch(url, {
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
      ...options,
    });

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
}

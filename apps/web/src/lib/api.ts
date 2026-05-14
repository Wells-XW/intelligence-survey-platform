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

// ── Analytics Types ───────────────────────────────────────────────────

export interface FrequencyItem {
  value: string;
  count: number;
  percentage: number;
}

export interface NumericStats {
  mean: number;
  median: number;
  mode: number[];
  std_dev: number;
  min_value: number;
  max_value: number;
  n: number;
}

export interface QuestionSummary {
  question_name: string;
  question_text: string;
  question_type: string;
  total_answers: number;
  skipped: number;
  frequencies?: FrequencyItem[] | null;
  numeric_stats?: NumericStats | null;
  word_cloud?: Record<string, unknown>[] | null;
  top_texts?: string[] | null;
}

export interface SurveySummaryResponse {
  survey_id: string;
  survey_title: string;
  total_responses: number;
  complete_responses: number;
  partial_responses: number;
  questions: QuestionSummary[];
}

export interface CronbachAlphaResult {
  scale_name: string;
  items: string[];
  n_items: number;
  n_valid_responses: number;
  alpha: number;
  item_variances: Record<string, number>;
  total_variance: number;
  interpretation: string;
}

export interface CrossTabResult {
  row_question: string;
  col_question: string;
  row_labels: string[];
  col_labels: string[];
  matrix: number[][];
  chi_square?: number | null;
  cramers_v?: number | null;
  n: number;
}

export interface ResponseQualityResult {
  total_responses: number;
  complete_responses: number;
  completion_rate: number;
  avg_completion_seconds: number;
  median_completion_seconds: number;
  speeder_count: number;
  speeder_threshold_seconds: number;
  straightliner_count: number;
  dropout_question?: string | null;
  dropout_count: number;
}

export interface SurveyResponseListItem {
  id: string;
  survey_id: string;
  respondent_id?: string | null;
  is_complete: boolean;
  completion_time_seconds?: number | null;
  submitted_at: string;
}

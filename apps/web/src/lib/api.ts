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

// ── AI Generation Types ────────────────────────────────────────────────

export interface AiGenerationRequest {
  topic: string;
  research_question: string;
  target_population: string;
  num_items?: number;
  language?: 'zh' | 'en';
  constructs?: string[];
  existing_scales?: string[];
  methodology_notes?: string;
  survey_id?: string;
}

export interface AiCostEstimate {
  estimated_tokens_input: number;
  estimated_tokens_output: number;
  estimated_cost_cents: number;
  estimated_cost_rmb: number;
  model: string;
  provider: string;
  is_low_cost: boolean;
  message: string;
}

export interface SqpQualitySummary {
  overall_quality: number;
  total_items: number;
  total_flags: number;
  estimated_cronbach_alpha: number;
  recommendation: string;
  summary: string;
}

export interface AiGenerationMeta {
  model: string;
  provider: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  estimated_cost_cents: number;
  route_reasoning: string;
}

export interface AiGenerationResponse {
  survey_json?: Record<string, unknown>;
  sqp_report?: SqpQualitySummary;
  meta: AiGenerationMeta;
  success: boolean;
  error?: string;
}

export interface SseProgressEvent {
  stage: string;
  message: string;
  progress_pct: number;
  data?: Record<string, unknown>;
}

// ── AI API Helpers ────────────────────────────────────────────────────

export async function estimateAiCost(
  req: AiGenerationRequest
): Promise<AiCostEstimate> {
  return api.post<AiCostEstimate>('/ai/estimate-cost', req);
}

export async function generateSurvey(
  req: AiGenerationRequest
): Promise<AiGenerationResponse> {
  return api.post<AiGenerationResponse>('/ai/generate', req);
}

export function generateSurveyStream(
  req: AiGenerationRequest,
  onEvent: (event: SseProgressEvent) => void,
  onError: (error: string) => void,
  onComplete: (result: AiGenerationResponse) => void
): AbortController {
  const controller = new AbortController();
  const token = useAuthStore.getState().accessToken;

  const fetchStream = async () => {
    try {
      const response = await fetch('/api/v1/ai/generate/stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(req),
        signal: controller.signal,
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({ detail: 'Stream error' }));
        onError(err.detail || 'SSE 连接失败');
        return;
      }

      const reader = response.body?.getReader();
      if (!reader) {
        onError('浏览器不支持流式读取');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let eventType = '';
        let eventData = '';

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6).trim();
          } else if (line === '' && eventData) {
            try {
              const parsed = JSON.parse(eventData) as SseProgressEvent;
              onEvent(parsed);

              if (eventType === 'done' && parsed.data) {
                onComplete({
                  success: true,
                  survey_json: parsed.data.survey_json as Record<string, unknown>,
                  sqp_report: parsed.data.sqp as SqpQualitySummary,
                  meta: parsed.data.meta as AiGenerationMeta,
                });
                return;
              }
              if (eventType === 'error') {
                onError(parsed.message);
                return;
              }
            } catch {
              // skip unparseable events
            }
            eventType = '';
            eventData = '';
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      onError(err instanceof Error ? err.message : 'SSE 连接异常');
    }
  };

  fetchStream();
  return controller;
}

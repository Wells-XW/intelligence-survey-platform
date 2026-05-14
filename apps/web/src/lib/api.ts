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
  // T9 extended metrics
  missing_patterns?: {
    per_item_missing: Record<string, { count: number; rate: number }>;
    co_missing_pairs: Array<{ q1: string; q2: string; co_miss_count: number; rate: number }>;
    respondent_distribution: Array<{ missing_count: number; n_respondents: number }>;
  } | null;
  inconsistency_rate?: number | null;
  inconsistent_respondents?: number | null;
  response_time_distribution?: {
    quantiles: Record<string, number>;
    fast_threshold: number;
    slow_threshold: number;
    fast_respondents: number;
    slow_respondents: number;
  } | null;
  attention_check_pass_rate?: number | null;
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

// ── Knowledge Base Types ────────────────────────────────────────────────

export interface LiteratureResult {
  title: string;
  authors: string[];
  year?: number;
  journal?: string;
  abstract?: string;
  doi?: string;
  url?: string;
  source: 'pubmed' | 'semantic_scholar' | 'cnki_web';
  external_id?: string;
  keywords?: string[];
}

export interface LiteratureSearchResponse {
  results: LiteratureResult[];
  total_count: number;
  source: string;
  query: string;
  cached: boolean;
}

export interface ScaleItem {
  code: string;
  text: string;
  reverse_scored: boolean;
}

export interface ScaleResponse {
  id: string;
  name: string;
  discipline: string;
  description?: string;
  items?: ScaleItem[];
  cronbach_alpha?: number;
  cronbach_alpha_history?: Array<{ value: number; sample_n: number; year: number; citation: string }>;
  citations?: Array<{ title: string; authors: string; year: number; doi: string }>;
  language: string;
  source_type: string;
  created_at: string;
  updated_at: string;
}

export interface ScaleSearchResponse {
  results: ScaleResponse[];
  total_count: number;
}

export interface SavedReferenceResponse {
  id: string;
  title: string;
  authors?: string[];
  year?: number;
  journal?: string;
  abstract?: string;
  doi?: string;
  url?: string;
  source: string;
  external_id?: string;
  keywords?: string[];
  is_saved: boolean;
  notes?: string;
  created_at: string;
}

export interface SavedReferenceListResponse {
  items: SavedReferenceResponse[];
  total: number;
}

export interface KnowledgeEntryResponse {
  id: string;
  title: string;
  category: string;
  content?: Record<string, unknown>;
  tags?: string[];
  language: string;
  created_at: string;
}

export interface KnowledgeEntrySearchResponse {
  results: KnowledgeEntryResponse[];
  total_count: number;
}

export interface AiAssistedSearchRequest {
  topic: string;
  research_question?: string;
  include_literature?: boolean;
  include_scales?: boolean;
}

export interface AiAssistedSearchResponse {
  literature_findings: LiteratureResult[];
  related_scales: ScaleResponse[];
  ai_summary: string;
  scales_ai_extracted?: Array<{ name: string; items: ScaleItem[] }>;
  model_used: string;
  tokens_used: number;
}

export interface ScaleImportResponse {
  survey_id: string;
  items_added: number;
  survey_json: Record<string, unknown>;
}

// ── Knowledge Base API Helpers ──────────────────────────────────────────

export function searchLiterature(params: {
  query: string;
  source?: string;
  search_type?: string;
  year_from?: number;
  year_to?: number;
  max_results?: number;
}): Promise<LiteratureSearchResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) searchParams.set(k, String(v));
  });
  return api.get<LiteratureSearchResponse>(`/kb/search/literature?${searchParams.toString()}`);
}

export function searchScales(params: {
  query?: string;
  discipline?: string;
  language?: string;
  limit?: number;
  offset?: number;
}): Promise<ScaleSearchResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) searchParams.set(k, String(v));
  });
  return api.get<ScaleSearchResponse>(`/kb/search/scales?${searchParams.toString()}`);
}

export function getSavedReferences(params: {
  limit?: number;
  offset?: number;
}): Promise<SavedReferenceListResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) searchParams.set(k, String(v));
  });
  return api.get<SavedReferenceListResponse>(`/kb/references?${searchParams.toString()}`);
}

export function saveReference(data: {
  literature: LiteratureResult;
  notes?: string;
}): Promise<SavedReferenceResponse> {
  return api.post<SavedReferenceResponse>('/kb/references', data);
}

export function deleteReference(id: string): Promise<void> {
  return api.delete<void>(`/kb/references/${id}`);
}

export function aiAssistedSearch(
  data: AiAssistedSearchRequest
): Promise<AiAssistedSearchResponse> {
  return api.post<AiAssistedSearchResponse>('/kb/search/ai-assisted', data);
}

export function importScaleToSurvey(
  scaleId: string,
  surveyId: string,
  position: string = 'end'
): Promise<ScaleImportResponse> {
  return api.post<ScaleImportResponse>(`/kb/scales/${scaleId}/import`, {
    survey_id: surveyId,
    position,
  });
}

export function getScaleDetail(scaleId: string): Promise<ScaleResponse> {
  return api.get<ScaleResponse>(`/kb/scales/${scaleId}`);
}

export function searchEntries(params: {
  query?: string;
  category?: string;
  language?: string;
  limit?: number;
  offset?: number;
}): Promise<KnowledgeEntrySearchResponse> {
  const searchParams = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) searchParams.set(k, String(v));
  });
  return api.get<KnowledgeEntrySearchResponse>(`/kb/entries?${searchParams.toString()}`);
}

// ── Ethics & Compliance Types ───────────────────────────────────────────

export interface ComplianceFinding {
  dimension: string;
  issue: string;
  severity: string;
  evidence?: string | null;
  reference?: string | null;
}

export interface ComplianceSuggestion {
  priority: string;
  title: string;
  description: string;
  reference?: string | null;
}

export interface ComplianceCheckResponse {
  id: string;
  survey_id: string;
  check_type: string;
  status: string;
  risk_level: string;
  risk_score: number;
  findings: ComplianceFinding[];
  suggestions: ComplianceSuggestion[];
  items_checked: number;
  items_passed: number;
  items_warning: number;
  items_failed: number;
  checked_at: string;
}

export interface ComplianceHistoryResponse {
  survey_id: string;
  checks: ComplianceCheckResponse[];
  latest_risk_score?: number | null;
  latest_risk_level?: string | null;
  total_checks: number;
}

export interface ComplianceReportResponse {
  survey_id: string;
  survey_title: string;
  report_markdown: string;
  risk_score: number;
  risk_level: string;
  generated_at: string;
}

export interface ComplianceScanRequest {
  check_types?: string[] | null;
  include_ai_review?: boolean;
}

// ── Ethics & Compliance API Helpers ────────────────────────────────────

export function runComplianceScan(
  surveyId: string,
  body?: ComplianceScanRequest,
): Promise<ComplianceCheckResponse> {
  return api.post<ComplianceCheckResponse>(
    `/surveys/${surveyId}/compliance/scan`,
    body || {},
  );
}

export function getComplianceReport(
  surveyId: string,
): Promise<ComplianceReportResponse> {
  return api.get<ComplianceReportResponse>(
    `/surveys/${surveyId}/compliance/report`,
  );
}

export function getComplianceHistory(
  surveyId: string,
): Promise<ComplianceHistoryResponse> {
  return api.get<ComplianceHistoryResponse>(
    `/surveys/${surveyId}/compliance/history`,
  );
}

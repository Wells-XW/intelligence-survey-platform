import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Download, FileSpreadsheet, ChevronDown } from 'lucide-react';
import { toast } from 'sonner';
import { api } from '@/lib/api';
import type {
  SurveySummaryResponse,
  CronbachAlphaResult,
  CrossTabResult,
  ResponseQualityResult,
  SurveyResponseListItem,
} from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  BarChart,
  PieChart,
  HeatmapChart,
  ResponseDataTable,
  QualityIndicators,
  CronbachDisplay,
} from '@/features/analytics/components';
import {
  ANALYTICS_TABS,
  useAnalyticsStore,
} from '@/features/analytics/store';

type TabKey = 'summary' | 'crosstab' | 'reliability' | 'quality';

function useAnalyticsSummary(surveyId: string) {
  return useQuery({
    queryKey: ['analytics', surveyId, 'summary'],
    queryFn: () => api.get<SurveySummaryResponse>(`/surveys/${surveyId}/analytics/summary`),
  });
}

function useCronbachAlpha(surveyId: string, scaleItems: string | null) {
  const params = scaleItems ? `?scale_items=${encodeURIComponent(scaleItems)}` : '';
  return useQuery({
    queryKey: ['analytics', surveyId, 'reliability', scaleItems],
    queryFn: () =>
      api.get<CronbachAlphaResult[]>(`/surveys/${surveyId}/analytics/reliability${params}`),
    enabled: !!surveyId,
  });
}

function useCrossTab(surveyId: string, q1: string | null, q2: string | null) {
  return useQuery({
    queryKey: ['analytics', surveyId, 'crosstab', q1, q2],
    queryFn: () =>
      api.get<CrossTabResult>(
        `/surveys/${surveyId}/analytics/cross-tab?q1=${encodeURIComponent(q1!)}&q2=${encodeURIComponent(q2!)}`,
      ),
    enabled: !!surveyId && !!q1 && !!q2,
  });
}

function useResponseQuality(surveyId: string) {
  return useQuery({
    queryKey: ['analytics', surveyId, 'quality'],
    queryFn: () => api.get<ResponseQualityResult>(`/surveys/${surveyId}/analytics/response-quality`),
  });
}

function useResponses(surveyId: string) {
  return useQuery({
    queryKey: ['responses', surveyId],
    queryFn: () => api.get<SurveyResponseListItem[]>(`/surveys/${surveyId}/responses?limit=200`),
  });
}

export function AnalyticsDashboardPage() {
  const { id } = useParams<{ id: string }>();
  const surveyId = id!;
  const { activeTab, setActiveTab } = useAnalyticsStore();

  const { data: summary, isLoading: summaryLoading } = useAnalyticsSummary(surveyId);
  const { data: quality, isLoading: qualityLoading } = useResponseQuality(surveyId);
  const { data: responses, isLoading: responsesLoading } = useResponses(surveyId);

  const handleExport = (format: 'csv' | 'xlsx') => {
    const url = `/api/v1/surveys/${surveyId}/responses/export?format=${format}`;
    const token = localStorage.getItem('access_token');
    const fetchUrl = url.startsWith('http') ? url : url;

    fetch(fetchUrl, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((res) => res.blob())
      .then((blob) => {
        const downloadUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = downloadUrl;
        a.download = `survey_${surveyId.slice(0, 8)}_responses.${format === 'xlsx' ? 'csv' : format}`;
        a.click();
        URL.revokeObjectURL(downloadUrl);
        toast.success('数据导出成功');
      })
      .catch(() => toast.error('导出失败'));
  };

  if (summaryLoading) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-8">
        <Skeleton className="mb-8 h-8 w-48" />
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-64 w-full rounded-xl" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-semibold text-gray-900">
            {summary?.survey_title ?? '问卷分析'}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {summary?.total_responses ?? 0} 份回复 ·{' '}
            {summary?.complete_responses ?? 0} 份完整
          </p>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">
              <Download className="mr-2 h-4 w-4" />
              导出
              <ChevronDown className="ml-1 h-3 w-3" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => handleExport('csv')}>
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              导出 CSV
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => handleExport('xlsx')}>
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              导出 Excel (CSV格式)
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {/* Tab Navigation */}
      <div className="mb-6 flex gap-1 rounded-lg bg-muted p-1">
        {ANALYTICS_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.key
                ? 'bg-surface text-gray-900 shadow-sm'
                : 'text-muted-foreground hover:text-gray-700'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {activeTab === 'summary' && summary && (
        <SummaryTab summary={summary} quality={quality} />
      )}
      {activeTab === 'crosstab' && summary && (
        <CrossTabTab surveyId={surveyId} questions={summary.questions} />
      )}
      {activeTab === 'reliability' && summary && (
        <ReliabilityTab surveyId={surveyId} questions={summary.questions} />
      )}
      {activeTab === 'quality' && (
        <QualityTab
          quality={quality}
          qualityLoading={qualityLoading}
          responses={responses}
          responsesLoading={responsesLoading}
        />
      )}
    </div>
  );
}

// ── Summary Tab ───────────────────────────────────────────────────────

function SummaryTab({
  summary,
  quality,
}: {
  summary: SurveySummaryResponse;
  quality?: ResponseQualityResult;
}) {
  return (
    <div className="space-y-6">
      {/* Quality cards at top */}
      {quality && <QualityIndicators {...quality} />}

      {/* Per-question charts */}
      {summary.questions.map((q) => (
        <Card key={q.question_name}>
          <CardContent className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h3 className="font-medium text-gray-900">{q.question_text}</h3>
                <p className="text-xs text-muted-foreground">
                  {q.question_name} · {q.question_type} · {q.total_answers} 回答
                  {q.skipped > 0 && ` · ${q.skipped} 跳过`}
                </p>
              </div>
            </div>

            {/* Categorical: bar chart */}
            {q.frequencies && q.frequencies.length > 0 && (
              <BarChart
                data={q.frequencies.map((f) => ({
                  label: f.value,
                  value: f.count,
                }))}
                height={250}
              />
            )}

            {/* Numeric: basic stats display */}
            {q.numeric_stats && (
              <div className="mt-2 grid grid-cols-3 gap-3 text-center sm:grid-cols-6">
                {[
                  ['均值', q.numeric_stats.mean],
                  ['中位数', q.numeric_stats.median],
                  ['标准差', q.numeric_stats.std_dev],
                  ['最小值', q.numeric_stats.min_value],
                  ['最大值', q.numeric_stats.max_value],
                  ['样本量', q.numeric_stats.n],
                ].map(([label, val]) => (
                  <div key={label} className="rounded-lg bg-muted/50 p-3">
                    <p className="text-xs text-muted-foreground">{label}</p>
                    <p className="mt-1 text-lg font-semibold tabular-nums">
                      {typeof val === 'number' ? val.toFixed(2) : val}
                    </p>
                  </div>
                ))}
              </div>
            )}

            {/* Text: top responses */}
            {q.top_texts && q.top_texts.length > 0 && (
              <div className="mt-2 space-y-1">
                <p className="text-xs text-muted-foreground">常见回答:</p>
                {q.top_texts.map((text, i) => (
                  <p key={i} className="rounded bg-muted/30 px-3 py-1.5 text-sm">
                    {text}
                  </p>
                ))}
              </div>
            )}

            {/* No data */}
            {!q.frequencies && !q.numeric_stats && !q.top_texts && (
              <p className="py-4 text-center text-sm text-muted-foreground">
                暂无足够数据
              </p>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ── Cross-Tab Tab ─────────────────────────────────────────────────────

function CrossTabTab({
  surveyId,
  questions,
}: {
  surveyId: string;
  questions: SurveySummaryResponse['questions'];
}) {
  const categoricalQuestions = questions.filter(
    (q) => q.question_type === 'radiogroup' || q.question_type === 'dropdown' || q.question_type === 'boolean',
  );

  const [rowQ, setRowQ] = useState<string | null>(
    categoricalQuestions[0]?.question_name ?? null,
  );
  const [colQ, setColQ] = useState<string | null>(
    categoricalQuestions[1]?.question_name ?? categoricalQuestions[0]?.question_name ?? null,
  );

  const { data: crossTab, isLoading } = useCrossTab(surveyId, rowQ, colQ);

  if (categoricalQuestions.length < 2) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          交叉分析需要至少2个分类变量（如单选题、下拉题）
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-4">
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">行变量 (Row)</label>
          <select
            value={rowQ ?? ''}
            onChange={(e) => setRowQ(e.target.value || null)}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm"
          >
            {categoricalQuestions.map((q) => (
              <option key={q.question_name} value={q.question_name}>
                {q.question_text}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs text-muted-foreground">列变量 (Column)</label>
          <select
            value={colQ ?? ''}
            onChange={(e) => setColQ(e.target.value || null)}
            className="rounded-md border border-border bg-surface px-3 py-1.5 text-sm"
          >
            {categoricalQuestions.map((q) => (
              <option key={q.question_name} value={q.question_name}>
                {q.question_text}
              </option>
            ))}
          </select>
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-96 w-full rounded-xl" />
      ) : crossTab ? (
        <Card>
          <CardContent className="p-5">
            <HeatmapChart
              title={`${rowQ} × ${colQ} 交叉表 (n=${crossTab.n})`}
              xLabels={crossTab.col_labels}
              yLabels={crossTab.row_labels}
              data={crossTab.matrix}
              height={Math.max(300, crossTab.row_labels.length * 50 + 100)}
            />
            {crossTab.chi_square != null && (
              <p className="mt-3 text-center text-xs text-muted-foreground">
                χ² = {crossTab.chi_square.toFixed(4)}
              </p>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            请选择两个变量
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Reliability Tab ───────────────────────────────────────────────────

function ReliabilityTab({
  surveyId,
  questions,
}: {
  surveyId: string;
  questions: SurveySummaryResponse['questions'];
}) {
  const ratingQuestions = questions.filter((q) => q.question_type === 'rating');
  const [selectedItems, setSelectedItems] = useState<string[]>(
    ratingQuestions.map((q) => q.question_name),
  );
  const scaleItemsStr = selectedItems.length >= 2 ? selectedItems.join(',') : null;

  const { data: results, isLoading } = useCronbachAlpha(surveyId, scaleItemsStr);

  if (ratingQuestions.length < 2) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-sm text-muted-foreground">
          信度分析需要至少2个评分题（Likert 量表题）。当前问卷中评分题不足。
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <label className="mb-2 block text-sm font-medium text-gray-700">
          选择量表题目
        </label>
        <div className="flex flex-wrap gap-2">
          {ratingQuestions.map((q) => {
            const isSelected = selectedItems.includes(q.question_name);
            return (
              <button
                key={q.question_name}
                onClick={() =>
                  setSelectedItems((prev) =>
                    isSelected
                      ? prev.filter((n) => n !== q.question_name)
                      : [...prev, q.question_name],
                  )
                }
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  isSelected
                    ? 'bg-accent text-white'
                    : 'bg-muted text-muted-foreground hover:bg-muted/80'
                }`}
              >
                {q.question_text}
              </button>
            );
          })}
        </div>
      </div>

      {isLoading ? (
        <Skeleton className="h-32 w-full rounded-xl" />
      ) : results && results.length > 0 ? (
        <div className="space-y-3">
          {results.map((r) => (
            <CronbachDisplay key={r.scale_name} {...r} />
          ))}
        </div>
      ) : (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            请至少选择 2 个题目来计算 Cronbach's α
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Quality Tab ───────────────────────────────────────────────────────

function QualityTab({
  quality,
  qualityLoading,
  responses,
  responsesLoading,
}: {
  quality?: ResponseQualityResult;
  qualityLoading: boolean;
  responses?: SurveyResponseListItem[];
  responsesLoading: boolean;
}) {
  return (
    <div className="space-y-6">
      {qualityLoading ? (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} className="h-28 w-full rounded-xl" />
          ))}
        </div>
      ) : quality ? (
        <QualityIndicators {...quality} />
      ) : null}

      <Card>
        <CardContent className="p-5">
          <h3 className="mb-4 font-medium text-gray-900">回复列表</h3>
          {responsesLoading ? (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-10 w-full" />
              ))}
            </div>
          ) : responses ? (
            <ResponseDataTable responses={responses} />
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

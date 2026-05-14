import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  AiGenerationForm,
  ProgressPanel,
  SqpReportCard,
  CostBadge,
} from '@/features/ai-generation/components';
import { useAiGenerationStore } from '@/features/ai-generation/store';
import { api } from '@/lib/api';

export function AiGenerationPage() {
  const navigate = useNavigate();
  const { result, error, cost, isGenerating, reset } = useAiGenerationStore();
  const [showResult, setShowResult] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedId, setSavedId] = useState<string | null>(null);

  const handleGenerateStart = () => {
    setShowResult(false);
    setSavedId(null);
  };

  const handleGenerateComplete = () => {
    setShowResult(true);
  };

  const handleSaveToSurvey = async () => {
    if (!result?.survey_json) return;
    setSaving(true);
    try {
      const surveyData = result.survey_json as {
        survey?: { title?: string; description?: string };
        title?: string;
        description?: string;
      };
      const title =
        surveyData?.survey?.title ||
        surveyData?.title ||
        'AI 生成的问卷';
      const description =
        surveyData?.survey?.description ||
        surveyData?.description ||
        '';

      const created = await api.post<{ id: string }>('/surveys', {
        title,
        description,
        json_content: result.survey_json,
      });
      setSavedId(created.id);
    } catch (err) {
      console.error('Failed to save survey:', err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">AI 问卷生成</h1>
        <p className="text-muted-foreground mt-1">
          输入研究主题和问题，AI 将生成方法学规范的学术调查问卷，并自动评估问卷质量（SQP v2.1）。
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        {/* Form — left side */}
        <div className="lg:col-span-3 space-y-6">
          {/* Info Banner */}
          <div className="rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-800">
            <strong>DeepSeek 驱动</strong> — 每份 20 题问卷生成成本约 <strong>¥0.01</strong>，
            比 GPT-4o 便宜 <strong>40 倍</strong>。中文质量行业最优。
          </div>

          <AiGenerationForm
            onGenerateStart={handleGenerateStart}
            onGenerateComplete={handleGenerateComplete}
          />

          {/* Progress */}
          {(isGenerating || showResult) && <ProgressPanel />}

          {/* Error */}
          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {error}
            </div>
          )}
        </div>

        {/* Results — right side */}
        <div className="lg:col-span-2 space-y-4">
          {/* Cost display */}
          {result?.meta && <CostBadge meta={result.meta} cost={cost} />}

          {/* SQP Report */}
          {result?.sqp_report && <SqpReportCard report={result.sqp_report} />}

          {/* Actions on success */}
          {result?.success && result.survey_json && (
            <div className="rounded-lg border p-4 space-y-3">
              <h3 className="font-semibold text-sm">生成结果</h3>

              {/* Preview JSON summary */}
              <div className="rounded-md bg-muted p-3 text-xs max-h-48 overflow-y-auto">
                <pre className="whitespace-pre-wrap font-mono">
                  {JSON.stringify(
                    {
                      title: (result.survey_json as Record<string, unknown>)?.survey
                        ? ((result.survey_json as Record<string, unknown>).survey as Record<string, unknown>)?.title
                        : 'Survey',
                      sections: (
                        ((result.survey_json as Record<string, unknown>)?.survey as Record<string, unknown>)
                          ?.sections as Array<unknown>
                      )?.length || 0,
                      totalItems: (
                        ((result.survey_json as Record<string, unknown>)?.survey as Record<string, unknown>)
                          ?.sections as Array<Record<string, unknown>>
                      )?.reduce((sum, s) => sum + ((s.questions as Array<unknown>)?.length || 0), 0) || 0,
                    },
                    null,
                    2
                  )}
                </pre>
              </div>

              {/* Action buttons */}
              <div className="flex gap-2">
                {savedId ? (
                  <>
                    <button
                      onClick={() => navigate(`/survey/${savedId}`)}
                      className="flex-1 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
                    >
                      打开问卷编辑器
                    </button>
                    <button
                      onClick={() => navigate('/')}
                      className="rounded-md border px-4 py-2 text-sm"
                    >
                      返回列表
                    </button>
                  </>
                ) : (
                  <>
                    <button
                      onClick={handleSaveToSurvey}
                      disabled={saving}
                      className="flex-1 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
                    >
                      {saving ? '保存中...' : '保存到我的问卷'}
                    </button>
                    <button
                      onClick={reset}
                      className="rounded-md border px-4 py-2 text-sm"
                    >
                      重新生成
                    </button>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Feature highlights (shown before generation) */}
          {!result && !isGenerating && (
            <div className="rounded-lg border p-4 space-y-3 text-sm">
              <h3 className="font-semibold">AI 生成能力</h3>
              <ul className="space-y-2 text-muted-foreground">
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-0.5">✓</span>
                  方法学约束：内嵌 AAPOR/APA 标准，自动检测引导性偏差
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-0.5">✓</span>
                  SQP v2.1 评估：逐项信效度估计 + Cronbach's α 预测
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-0.5">✓</span>
                  中文优先：DeepSeek-R1 深度优化中文学术写作
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-0.5">✓</span>
                  PIPL 合规：自动生成知情同意书与数据保护声明
                </li>
                <li className="flex items-start gap-2">
                  <span className="text-emerald-500 mt-0.5">✓</span>
                  实时流式：SSE 推送生成进度，无需等待
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

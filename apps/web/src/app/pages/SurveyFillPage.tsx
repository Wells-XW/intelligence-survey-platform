import { useState, useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { CheckCircle, AlertCircle } from 'lucide-react';
import { toast } from 'sonner';
import { Model } from 'survey-core';
import { Survey } from 'survey-react-ui';
import 'survey-core/survey-core.css';
import { api } from '@/lib/api';
import type { Survey as SurveyType } from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

function usePublicSurvey(surveyId: string) {
  return useQuery({
    queryKey: ['survey', surveyId, 'public'],
    queryFn: async () => {
      // Public endpoint: allow fetching published surveys without auth
      // For MVP, we use the authenticated endpoint but with a public wrapper
      // In production, add a dedicated public endpoint
      return api.get<SurveyType>(`/surveys/${surveyId}`);
    },
  });
}

function useSubmitResponse(surveyId: string) {
  return useMutation({
    mutationFn: (data: { answers: Record<string, unknown>; metadata: Record<string, unknown> }) =>
      api.post(`/surveys/${surveyId}/responses`, {
        answers: data.answers,
        metadata: data.metadata,
        is_complete: true,
      }),
  });
}

export function SurveyFillPage() {
  const { id } = useParams<{ id: string }>();
  const surveyId = id!;
  const [searchParams] = useSearchParams();
  const respondentId = searchParams.get('rid') ?? undefined;

  const { data: survey, isLoading, error } = usePublicSurvey(surveyId);
  const submitMutation = useSubmitResponse(surveyId);

  const [piplConsent, setPiplConsent] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [startTime] = useState(() => Date.now());
  const [surveyModel, setSurveyModel] = useState<Model | null>(null);

  // Initialize SurveyJS model when survey data loads
  useEffect(() => {
    if (!survey) return;

    const model = new Model(survey.json_content);
    model.showCompleteButton = true;
    model.showPreviewBeforeComplete = 'showAllQuestions';
    model.completeText = '提交问卷';
    model.pageNextText = '下一页';
    model.pagePrevText = '上一页';
    model.questionTitlePattern = 'numTitleRequire';
    model.locale = 'zh-cn';

    model.onComplete.add((sender) => {
      if (!piplConsent) {
        toast.error('请先确认知情同意声明');
        return;
      }

      const completionTime = (Date.now() - startTime) / 1000;
      submitMutation.mutate(
        {
          answers: sender.data,
          metadata: {
            pipl_consent: true,
            completion_time_seconds: Math.round(completionTime * 10) / 10,
            user_agent: navigator.userAgent,
            respondent_id: respondentId,
          },
        },
        {
          onSuccess: () => {
            setSubmitted(true);
            toast.success('提交成功！感谢您的参与。');
          },
          onError: () => {
            toast.error('提交失败，请重试');
          },
        },
      );
    });

    setSurveyModel(model);

    return () => {
      model.dispose();
    };
  }, [survey, piplConsent, startTime, respondentId, submitMutation]);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-12">
        <Skeleton className="mb-4 h-8 w-64" />
        <Skeleton className="mb-2 h-4 w-full" />
        <Skeleton className="mb-2 h-4 w-3/4" />
        <Skeleton className="h-24 w-full rounded-xl" />
      </div>
    );
  }

  if (error || !survey) {
    return (
      <div className="mx-auto max-w-lg px-4 py-20 text-center">
        <AlertCircle className="mx-auto mb-4 h-12 w-12 text-muted-foreground/50" />
        <h1 className="text-xl font-semibold text-gray-900">问卷不可用</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          该问卷不存在或暂未开放。请联系问卷发布者获取有效的问卷链接。
        </p>
      </div>
    );
  }

  if (survey.status !== 'published') {
    return (
      <div className="mx-auto max-w-lg px-4 py-20 text-center">
        <AlertCircle className="mx-auto mb-4 h-12 w-12 text-yellow-500" />
        <h1 className="text-xl font-semibold text-gray-900">问卷尚未发布</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          该问卷目前处于「{survey.status === 'draft' ? '草稿' : '已关闭'}」状态，暂不接受填写。
        </p>
      </div>
    );
  }

  if (submitted) {
    return (
      <div className="mx-auto max-w-lg px-4 py-20 text-center">
        <CheckCircle className="mx-auto mb-4 h-16 w-16 text-green-500" />
        <h1 className="text-2xl font-semibold text-gray-900">提交成功</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          感谢您的参与！您的回复已被记录。
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* Survey Header */}
      <div className="mb-6">
        <h1 className="font-heading text-2xl font-semibold text-gray-900">
          {survey.title}
        </h1>
        {survey.description && (
          <p className="mt-2 text-sm text-muted-foreground">{survey.description}</p>
        )}
      </div>

      {/* PIPL Consent */}
      <Card className="mb-6 border-blue-200 bg-blue-50/50">
        <CardContent className="p-4">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={piplConsent}
              onChange={(e) => setPiplConsent(e.target.checked)}
              className="mt-1 h-4 w-4 rounded border-gray-300 text-accent focus:ring-accent"
            />
            <div className="text-sm">
              <p className="font-medium text-gray-800">知情同意声明</p>
              <p className="mt-1 text-muted-foreground">
                根据《中华人民共和国个人信息保护法》第18条，我已知晓：
                我的回答将被匿名化处理，仅用于学术研究目的。我不会被要求提供
                身份证号、银行账户等敏感个人信息。我有权随时退出调查。
              </p>
            </div>
          </label>
        </CardContent>
      </Card>

      {/* SurveyJS Survey Component */}
      {surveyModel && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <Survey model={surveyModel} />
        </div>
      )}
    </div>
  );
}

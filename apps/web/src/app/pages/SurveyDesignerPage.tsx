import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Save, Eye, Send, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, type Survey, type UpdateSurveyRequest } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import { Skeleton } from '@/components/ui/skeleton';
import { SurveyCreator } from '@/features/survey-designer/components/SurveyCreator';

function useSurvey(id: string) {
  return useQuery({
    queryKey: ['survey', id],
    queryFn: () => api.get<Survey>(`/surveys/${id}`),
    enabled: id !== 'new',
  });
}

function useSaveSurvey(id: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UpdateSurveyRequest) => api.put<Survey>(`/surveys/${id}`, data),
    onSuccess: (data) => {
      queryClient.setQueryData(['survey', id], data);
      queryClient.invalidateQueries({ queryKey: ['surveys'] });
      toast.success('问卷已保存');
    },
    onError: () => {
      toast.error('保存失败，请重试');
    },
  });
}

export function SurveyDesignerPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const isNew = id === 'new';

  // For new surveys, create first then navigate to the actual page
  useEffect(() => {
    if (isNew) {
      api
        .post<Survey>('/surveys', {
          title: '未命名问卷',
          json_content: { pages: [] },
        })
        .then((survey) => {
          navigate(`/survey/${survey.id}`, { replace: true });
        })
        .catch(() => {
          toast.error('创建问卷失败');
          navigate('/', { replace: true });
        });
    }
  }, [isNew, navigate]);

  if (isNew || !id) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return <SurveyDesignerEditor surveyId={id} />;
}

function SurveyDesignerEditor({ surveyId }: { surveyId: string }) {
  const { data: survey, isLoading } = useSurvey(surveyId);
  const saveSurvey = useSaveSurvey(surveyId);
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [surveyJson, setSurveyJson] = useState<Record<string, unknown>>({});
  const isSavingRef = useRef(false);

  // Sync local state when survey loads
  useEffect(() => {
    if (survey) {
      setTitle(survey.title);
      setSurveyJson(survey.json_content || { pages: [] });
    }
  }, [survey]);

  const handleSave = useCallback(() => {
    if (isSavingRef.current) return;
    isSavingRef.current = true;
    saveSurvey.mutate(
      { title, json_content: surveyJson },
      { onSettled: () => { isSavingRef.current = false; } },
    );
  }, [title, surveyJson, saveSurvey]);

  // Keyboard shortcut: Ctrl+S to save
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 's') {
        e.preventDefault();
        handleSave();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleSave]);

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      {/* Toolbar */}
      <header className="flex items-center gap-3 border-b bg-white px-4 py-2 shadow-sm">
        <Button variant="ghost" size="icon" onClick={() => navigate('/')} title="返回列表">
          <ArrowLeft className="h-4 w-4" />
        </Button>

        <Separator orientation="vertical" className="h-6" />

        <Input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="max-w-xs border-none bg-transparent text-lg font-medium shadow-none focus-visible:ring-0"
          placeholder="问卷标题"
        />

        <div className="flex-1" />

        <Button
          variant="outline"
          size="sm"
          onClick={handleSave}
          disabled={saveSurvey.isPending}
        >
          {saveSurvey.isPending ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-2 h-4 w-4" />
          )}
          保存
        </Button>

        <Button variant="outline" size="sm">
          <Eye className="mr-2 h-4 w-4" />
          预览
        </Button>

        <Button size="sm">
          <Send className="mr-2 h-4 w-4" />
          发布
        </Button>
      </header>

      {/* Editor */}
      <div className="flex-1 overflow-hidden">
        <SurveyCreator
          surveyJson={surveyJson}
          onJsonChange={setSurveyJson}
        />
      </div>
    </div>
  );
}

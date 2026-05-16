import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ArrowLeft, Save, Eye, Send, Share2, History, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { api, type Survey, type UpdateSurveyRequest } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Separator } from '@/components/ui/separator';
import {
  SurveyCreator,
  VersionHistoryPanel,
  ShareDialog,
  ConflictDialog,
  CollaboratorAvatars,
  QuestionLockOverlay,
} from '@/features/survey-designer/components';
import { useDesignerStore } from '@/features/survey-designer/store';
import { useCollabSocket } from '@/features/survey-designer/hooks/useCollabSocket';
import { useAuthStore } from '@/features/auth/store';

function useSurvey(id: string) {
  return useQuery({
    queryKey: ['survey', id],
    queryFn: () => api.get<Survey>(`/surveys/${id}`),
    enabled: id !== 'new',
  });
}

function useSaveSurvey(id: string, getConnectionId: () => string | null) {
  const queryClient = useQueryClient();
  const setConflictDialogOpen = useDesignerStore((s) => s.setConflictDialogOpen);
  const setConflictInfo = useDesignerStore((s) => s.setConflictInfo);

  return useMutation({
    mutationFn: (data: UpdateSurveyRequest) => {
      const connId = getConnectionId();
      // Custom header lets the server skip our own ws broadcast.
      // The shared ApiClient does not accept extra headers, so we use
      // fetch directly here.  Auth comes from the same store.
      return fetch(`/api/v1/surveys/${id}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...(connId ? { 'X-Collab-Connection-Id': connId } : {}),
          ...getAuthHeader(),
        },
        body: JSON.stringify(data),
      }).then(async (res) => {
        if (!res.ok) {
          let detail = `HTTP ${res.status}`;
          try {
            const body = await res.json();
            detail = body.detail || detail;
          } catch {
            /* ignore */
          }
          const err = { status: res.status, detail } as { status: number; detail: string };
          throw err;
        }
        return res.json() as Promise<Survey>;
      });
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['survey', id], data);
      queryClient.invalidateQueries({ queryKey: ['surveys'] });
      queryClient.invalidateQueries({ queryKey: ['surveyVersions', id] });
      toast.success('问卷已保存');
    },
    onError: (err: { status?: number; detail?: string }) => {
      if (err.status === 409) {
        // Version conflict — open dialog
        const match = err.detail?.match(/v(\d+).*v(\d+)/);
        setConflictInfo({
          expectedVersion: match ? parseInt(match[1]) : 0,
          serverVersion: match ? parseInt(match[2]) : 0,
        });
        setConflictDialogOpen(true);
      } else {
        toast.error(err.detail || '保存失败，请重试');
      }
    },
  });
}

/** Pull access token from the auth store. */
function getAuthHeader(): Record<string, string> {
  const token = useAuthStore.getState().accessToken;
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [surveyJson, setSurveyJson] = useState<Record<string, unknown>>({});
  const isSavingRef = useRef(false);
  const setShareDialogOpen = useDesignerStore((s) => s.setShareDialogOpen);
  const setVersionPanelOpen = useDesignerStore((s) => s.setVersionPanelOpen);

  // ── Real-time collaboration socket ───────────────────────────────
  const socketRef = useCollabSocket(surveyId);
  const getConnectionId = useCallback(
    () => socketRef.current?.getConnectionId() ?? null,
    [socketRef],
  );
  const saveSurvey = useSaveSurvey(surveyId, getConnectionId);

  // Sync local state when survey loads
  useEffect(() => {
    if (survey) {
      setTitle(survey.title);
      setSurveyJson(survey.json_content || { pages: [] });
    }
  }, [survey]);

  // Tell the server which question we're focused on.
  const handleSelectedQuestionChange = useCallback(
    (questionId: string | null) => {
      socketRef.current?.acquireFocus(questionId);
    },
    [socketRef],
  );

  // Release focus on unmount so collaborators see the lock disappear
  // immediately instead of waiting for the 60s TTL.
  useEffect(() => {
    return () => {
      socketRef.current?.releaseFocus();
    };
  }, [socketRef]);

  const handleSave = useCallback(() => {
    if (isSavingRef.current) return;
    isSavingRef.current = true;
    saveSurvey.mutate(
      {
        title,
        json_content: surveyJson,
        expected_version: survey?.version, // optimistic lock
      },
      { onSettled: () => { isSavingRef.current = false; } },
    );
  }, [title, surveyJson, survey, saveSurvey]);

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

        <CollaboratorAvatars />

        <Separator orientation="vertical" className="h-6" />

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

        <Button
          variant="outline"
          size="sm"
          onClick={() => setVersionPanelOpen(true)}
          title="版本历史"
        >
          <History className="mr-2 h-4 w-4" />
          版本
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={() => setShareDialogOpen(true)}
          title="协作与分享"
        >
          <Share2 className="mr-2 h-4 w-4" />
          分享
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
      <div className="relative flex-1 overflow-hidden">
        <SurveyCreator
          surveyJson={surveyJson}
          onJsonChange={setSurveyJson}
          onSelectedQuestionChange={handleSelectedQuestionChange}
        />
        <QuestionLockOverlay />
      </div>

      {/* Dialogs */}
      <VersionHistoryPanel surveyId={surveyId} />
      <ShareDialog surveyId={surveyId} />
      <ConflictDialog surveyId={surveyId} />
    </div>
  );
}

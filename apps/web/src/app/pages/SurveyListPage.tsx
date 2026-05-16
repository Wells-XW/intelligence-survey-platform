import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, FileText, MoreVertical, Trash2, Copy, BarChart3, Send } from 'lucide-react';
import { toast } from 'sonner';
import { api, type SurveyListItem } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';

function useSurveys() {
  return useQuery({
    queryKey: ['surveys'],
    queryFn: () => api.get<SurveyListItem[]>('/surveys'),
  });
}

function useCreateSurvey() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  return useMutation({
    mutationFn: () =>
      api.post<SurveyListItem>('/surveys', {
        title: '未命名问卷',
        json_content: { pages: [] },
      }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['surveys'] });
      navigate(`/survey/${data.id}`);
      toast.success('问卷已创建');
    },
    onError: () => {
      toast.error('创建失败，请重试');
    },
  });
}

function useDeleteSurvey() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (id: string) => api.delete(`/surveys/${id}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveys'] });
      toast.success('问卷已删除');
    },
    onError: () => {
      toast.error('删除失败，请重试');
    },
  });
}

function formatDate(dateStr: string) {
  return new Date(dateStr).toLocaleDateString('zh-CN', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  });
}

const statusLabels: Record<string, string> = {
  draft: '草稿',
  published: '已发布',
  closed: '已关闭',
};

const statusColors: Record<string, string> = {
  draft: 'bg-yellow-100 text-yellow-800',
  published: 'bg-green-100 text-green-800',
  closed: 'bg-gray-100 text-gray-600',
};

export function SurveyListPage() {
  const { data: surveys, isLoading } = useSurveys();
  const createSurvey = useCreateSurvey();
  const deleteSurvey = useDeleteSurvey();
  const [search, setSearch] = useState('');

  const filteredSurveys = surveys?.filter((s) =>
    s.title.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="mx-auto max-w-4xl px-4 py-8">
      {/* Header */}
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-semibold text-gray-900">我的问卷</h1>
          <p className="mt-1 text-sm text-muted-foreground">管理和创建学术调查问卷</p>
        </div>
        <Button onClick={() => createSurvey.mutate()} disabled={createSurvey.isPending}>
          <Plus className="mr-2 h-4 w-4" />
          创建问卷
        </Button>
      </div>

      {/* Search */}
      <div className="mb-6">
        <Input
          placeholder="搜索问卷..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
      </div>

      {/* Survey List */}
      {isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardContent className="p-6">
                <Skeleton className="h-5 w-48" />
                <Skeleton className="mt-2 h-4 w-32" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : filteredSurveys && filteredSurveys.length > 0 ? (
        <div className="space-y-3">
          {filteredSurveys.map((survey) => (
            <SurveyCard key={survey.id} survey={survey} onDelete={() => deleteSurvey.mutate(survey.id)} />
          ))}
        </div>
      ) : (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center py-12 text-center">
            <FileText className="mb-3 h-10 w-10 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">尚无问卷</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => createSurvey.mutate()}
            >
              <Plus className="mr-2 h-3 w-3" />
              创建第一份问卷
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SurveyCard({
  survey,
  onDelete,
}: {
  survey: SurveyListItem;
  onDelete: () => void;
}) {
  const navigate = useNavigate();

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-sm"
      onClick={() => navigate(`/survey/${survey.id}`)}
    >
      <CardContent className="flex items-center justify-between p-5">
        <div className="flex-1">
          <h3 className="font-medium text-gray-900">{survey.title}</h3>
          <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
            <span>{formatDate(survey.updated_at)}</span>
            <span>·</span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusColors[survey.status]}`}>
              {statusLabels[survey.status]}
            </span>
            <span>·</span>
            <span>v{survey.version}</span>
          </div>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="icon">
              <MoreVertical className="h-4 w-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => navigate(`/survey/${survey.id}`)}>
              <FileText className="mr-2 h-4 w-4" />
              编辑
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/survey/${survey.id}/analytics`)}>
              <BarChart3 className="mr-2 h-4 w-4" />
              分析
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => navigate(`/survey/${survey.id}/distribution`)}>
              <Send className="mr-2 h-4 w-4" />
              样本发放
            </DropdownMenuItem>
            <DropdownMenuItem
              onClick={() => {
                const fillUrl = `${window.location.origin}/survey/${survey.id}/fill`;
                navigator.clipboard.writeText(fillUrl);
                toast.success('填写链接已复制到剪贴板');
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              复制填写链接
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-red-600"
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
            >
              <Trash2 className="mr-2 h-4 w-4" />
              删除
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </CardContent>
    </Card>
  );
}

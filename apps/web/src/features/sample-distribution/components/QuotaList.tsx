import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2, Pause, Play } from 'lucide-react';
import toast from 'sonner';
import {
  getQuotas,
  createQuota,
  updateQuota,
  deleteQuota,
  type QuotaDefinition,
} from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

const DIMENSIONS = ['gender', 'age_group', 'education', 'region', 'income', 'occupation'] as const;
const DIMENSION_LABELS: Record<string, string> = {
  gender: '性别',
  age_group: '年龄段',
  education: '教育',
  region: '地区',
  income: '收入',
  occupation: '职业',
};

interface Props {
  surveyId: string;
}

export function QuotaList({ surveyId }: Props) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: '',
    dimension: 'gender',
    target_count: 50,
    criteria_key: '',
    criteria_value: '',
  });

  const { data: quotas, isLoading } = useQuery({
    queryKey: ['quotas', surveyId],
    queryFn: () => getQuotas(surveyId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createQuota(surveyId, {
        name: form.name,
        dimension: form.dimension,
        target_count: form.target_count,
        criteria: { [form.criteria_key]: form.criteria_value },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quotas', surveyId] });
      queryClient.invalidateQueries({ queryKey: ['distribution-dashboard', surveyId] });
      setShowForm(false);
      setForm({ name: '', dimension: 'gender', target_count: 50, criteria_key: '', criteria_value: '' });
      toast.success('配额已创建');
    },
    onError: () => toast.error('创建失败'),
  });

  const toggleMutation = useMutation({
    mutationFn: ({ qid, active }: { qid: string; active: boolean }) =>
      updateQuota(surveyId, qid, { is_active: active }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quotas', surveyId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (qid: string) => deleteQuota(surveyId, qid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['quotas', surveyId] });
      queryClient.invalidateQueries({ queryKey: ['distribution-dashboard', surveyId] });
      toast.success('配额已删除');
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2].map((i) => (
          <Skeleton key={i} className="h-20 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Create Quota Form */}
      {!showForm ? (
        <Button onClick={() => setShowForm(true)}>
          <Plus className="h-4 w-4 mr-1" />
          创建配额
        </Button>
      ) : (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="py-4 space-y-3">
            <h4 className="font-semibold text-sm">创建配额</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Input
                placeholder="配额名称 (如: 男性 ≥ 50)"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
              <select
                className="w-full rounded-md border border-input bg-surface px-3 py-2 text-sm"
                value={form.dimension}
                onChange={(e) => setForm({ ...form, dimension: e.target.value })}
              >
                {DIMENSIONS.map((d) => (
                  <option key={d} value={d}>
                    {DIMENSION_LABELS[d] || d}
                  </option>
                ))}
              </select>
              <Input
                type="number"
                placeholder="目标人数"
                value={form.target_count}
                min={1}
                onChange={(e) =>
                  setForm({ ...form, target_count: Math.max(1, Number(e.target.value) || 0) })
                }
              />
              <div className="flex gap-2">
                <Input
                  className="w-1/2"
                  placeholder="条件键 (如: gender)"
                  value={form.criteria_key}
                  onChange={(e) => setForm({ ...form, criteria_key: e.target.value })}
                />
                <Input
                  className="w-1/2"
                  placeholder="条件值 (如: 男)"
                  value={form.criteria_value}
                  onChange={(e) => setForm({ ...form, criteria_value: e.target.value })}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!form.name.trim() || !form.criteria_key.trim() || !form.criteria_value.trim()}
                onClick={() => createMutation.mutate()}
              >
                创建
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>
                取消
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Quota List */}
      {(!quotas || quotas.length === 0) ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <p>尚无配额定义</p>
            <p className="text-xs mt-1">创建配额可限制特定人群的响应数量</p>
          </CardContent>
        </Card>
      ) : (
        quotas.map((q) => {
          const fillColor =
            q.fill_rate >= 80 ? 'bg-green-500' : q.fill_rate >= 50 ? 'bg-amber-500' : 'bg-red-500';
          return (
            <Card key={q.id} className={cn(!q.is_active && 'opacity-60')}>
              <CardContent className="pt-4">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{q.name}</span>
                      {!q.is_active && (
                        <Badge variant="secondary" className="text-xs bg-gray-100">
                          已暂停
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      {DIMENSION_LABELS[q.dimension] || q.dimension} ·{' '}
                      {Object.entries(q.criteria).map(([k, v]) => `${k}=${v}`).join(', ')}
                    </p>
                  </div>
                  <div className="flex gap-1">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => toggleMutation.mutate({ qid: q.id, active: !q.is_active })}
                    >
                      {q.is_active ? (
                        <Pause className="h-3.5 w-3.5" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        if (confirm(`确定删除配额「${q.name}」？`)) {
                          deleteMutation.mutate(q.id);
                        }
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5 text-red-500" />
                    </Button>
                  </div>
                </div>

                {/* Progress Bar */}
                <div>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-muted-foreground">
                      {q.current_count} / {q.target_count}
                    </span>
                    <span
                      className={cn(
                        'font-medium',
                        q.fill_rate >= 80
                          ? 'text-green-600'
                          : q.fill_rate >= 50
                            ? 'text-amber-600'
                            : 'text-red-600',
                      )}
                    >
                      {q.fill_rate}%
                    </span>
                  </div>
                  <div className="h-2.5 rounded-full bg-muted overflow-hidden">
                    <div
                      className={cn('h-full rounded-full transition-all', fillColor)}
                      style={{ width: `${Math.min(q.fill_rate, 100)}%` }}
                    />
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })
      )}
    </div>
  );
}

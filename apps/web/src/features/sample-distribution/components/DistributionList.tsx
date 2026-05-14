import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Send, BellRing, Eye } from 'lucide-react';
import toast from 'sonner';
import {
  getDistributions,
  getSampleGroups,
  createDistribution,
  sendDistribution,
  remindDistribution,
  type DistributionCampaign,
  type SampleGroup,
} from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface Props {
  surveyId: string;
}

function DistributionStatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    draft: 'bg-gray-100 text-gray-600',
    sending: 'bg-blue-100 text-blue-700',
    sent: 'bg-green-100 text-green-700',
    completed: 'bg-purple-100 text-purple-700',
  };
  const labels: Record<string, string> = {
    draft: '草稿',
    sending: '发送中',
    sent: '已发送',
    completed: '已完成',
  };
  return (
    <Badge variant="secondary" className={cn('text-xs', colors[status] || '')}>
      {labels[status] || status}
    </Badge>
  );
}

export function DistributionList({ surveyId }: Props) {
  const queryClient = useQueryClient();
  const [showForm, setShowForm] = useState(false);
  const [formName, setFormName] = useState('');
  const [selectedGroupId, setSelectedGroupId] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const { data: distributions, isLoading } = useQuery({
    queryKey: ['distributions', surveyId],
    queryFn: () => getDistributions(surveyId),
  });

  const { data: groups } = useQuery({
    queryKey: ['sample-groups', surveyId],
    queryFn: () => getSampleGroups(surveyId),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      createDistribution(surveyId, {
        sample_group_id: selectedGroupId,
        name: formName,
        body_template: {
          text: '您好，诚邀您参与本次学术问卷调查。点击下方链接开始填写：',
          link_label: '开始填写问卷',
        },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['distributions', surveyId] });
      setShowForm(false);
      setFormName('');
      setSelectedGroupId('');
      toast.success('发放已创建');
    },
    onError: () => toast.error('创建失败，请确保问卷已发布'),
  });

  const sendMutation = useMutation({
    mutationFn: (did: string) => sendDistribution(surveyId, did),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['distributions', surveyId] });
      toast.success(`已处理 ${data.recipients_processed} 位受访者`);
    },
    onError: () => toast.error('发送失败'),
  });

  const remindMutation = useMutation({
    mutationFn: (did: string) => remindDistribution(surveyId, did),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['distributions', surveyId] });
      toast.success(`已提醒 ${data.recipients_processed} 位受访者`);
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
      {/* Create Distribution */}
      {!showForm ? (
        <Button onClick={() => setShowForm(true)} disabled={!groups?.length}>
          <Plus className="h-4 w-4 mr-1" />
          创建发放
        </Button>
      ) : (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="py-4 space-y-3">
            <h4 className="font-semibold text-sm">创建发放</h4>
            <Input
              placeholder="发放名称"
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
            />
            <select
              className="w-full rounded-md border border-input bg-surface px-3 py-2 text-sm"
              value={selectedGroupId}
              onChange={(e) => setSelectedGroupId(e.target.value)}
            >
              <option value="">选择样本组...</option>
              {(groups || []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name} ({g.recipient_count} 人)
                </option>
              ))}
            </select>
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={!formName.trim() || !selectedGroupId}
                onClick={() => createMutation.mutate()}
              >
                创建
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowForm(false)}
              >
                取消
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Distribution List */}
      {(!distributions || distributions.length === 0) ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <Send className="mx-auto h-8 w-8 mb-2 opacity-40" />
            <p>尚无发放记录</p>
          </CardContent>
        </Card>
      ) : (
        distributions.map((d) => (
          <Card key={d.id}>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{d.name}</span>
                    <DistributionStatusBadge status={d.status} />
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    已发送 {d.sent_count} · 已查看 {d.opened_count} · 已完成{' '}
                    {d.completed_count}
                  </p>
                </div>
                <div className="flex gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setExpandedId(expandedId === d.id ? null : d.id)
                    }
                  >
                    <Eye className="h-3.5 w-3.5 mr-1" />
                    详情
                  </Button>
                  {(d.status === 'draft' || d.status === 'sent') && (
                    <>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => sendMutation.mutate(d.id)}
                        disabled={sendMutation.isPending}
                      >
                        <Send className="h-3.5 w-3.5 mr-1" />
                        发送
                      </Button>
                      {d.status === 'sent' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => remindMutation.mutate(d.id)}
                          disabled={remindMutation.isPending}
                        >
                          <BellRing className="h-3.5 w-3.5 mr-1" />
                          提醒
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </div>

              {expandedId === d.id && (
                <div className="mt-3 pt-3 border-t text-sm text-muted-foreground space-y-1">
                  <p>
                    样本组: {d.sample_group_name || d.sample_group_id.slice(0, 8)}
                  </p>
                  <p>创建时间: {new Date(d.created_at).toLocaleString('zh-CN')}</p>
                </div>
              )}
            </CardContent>
          </Card>
        ))
      )}
    </div>
  );
}

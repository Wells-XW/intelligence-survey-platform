import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Pencil, Trash2, ChevronDown, Upload, UserPlus } from 'lucide-react';
import { toast } from 'sonner';
import {
  getSampleGroups,
  createSampleGroup,
  updateSampleGroup,
  deleteSampleGroup,
  getRecipients,
  addRecipient,
  deleteRecipient,
  importRecipientsCSV,
  type SampleGroup,
  type Recipient,
} from '@/lib/api';
import { useSampleDistributionStore } from '../store';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

interface Props {
  surveyId: string;
}

function StatusBadge({ status }: { status: Recipient['status'] }) {
  const colors: Record<string, string> = {
    pending: 'bg-gray-100 text-gray-600',
    sent: 'bg-blue-100 text-blue-700',
    opened: 'bg-cyan-100 text-cyan-700',
    started: 'bg-purple-100 text-purple-700',
    completed: 'bg-green-100 text-green-700',
    bounced: 'bg-red-100 text-red-700',
    opted_out: 'bg-orange-100 text-orange-700',
  };
  const labels: Record<string, string> = {
    pending: '待发送',
    sent: '已发送',
    opened: '已查看',
    started: '已开始',
    completed: '已完成',
    bounced: '退信',
    opted_out: '退出',
  };
  return (
    <Badge variant="secondary" className={cn('text-xs', colors[status] || '')}>
      {labels[status] || status}
    </Badge>
  );
}

export function SampleGroupList({ surveyId }: Props) {
  const queryClient = useQueryClient();
  const { selectedGroupId, setSelectedGroupId, importDialogOpen, setImportDialogOpen } =
    useSampleDistributionStore();
  const [newGroupName, setNewGroupName] = useState('');
  const [editingGroup, setEditingGroup] = useState<SampleGroup | null>(null);
  const [newRecipient, setNewRecipient] = useState({ email: '', name: '' });

  const { data: groups, isLoading } = useQuery({
    queryKey: ['sample-groups', surveyId],
    queryFn: () => getSampleGroups(surveyId),
  });

  const { data: recipients } = useQuery({
    queryKey: ['recipients', surveyId, selectedGroupId],
    queryFn: () => getRecipients(surveyId, selectedGroupId!, { limit: 200 }),
    enabled: !!selectedGroupId,
  });

  const createMutation = useMutation({
    mutationFn: (name: string) => createSampleGroup(surveyId, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sample-groups', surveyId] });
      setNewGroupName('');
      toast.success('样本组已创建');
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ gid, name }: { gid: string; name: string }) =>
      updateSampleGroup(surveyId, gid, { name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sample-groups', surveyId] });
      setEditingGroup(null);
      toast.success('样本组已更新');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (gid: string) => deleteSampleGroup(surveyId, gid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sample-groups', surveyId] });
      if (selectedGroupId) setSelectedGroupId(null);
      toast.success('样本组已删除');
    },
  });

  const addRecipientMutation = useMutation({
    mutationFn: (data: { email: string; name: string }) =>
      addRecipient(surveyId, selectedGroupId!, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recipients', surveyId, selectedGroupId] });
      queryClient.invalidateQueries({ queryKey: ['sample-groups', surveyId] });
      setNewRecipient({ email: '', name: '' });
      toast.success('受访者已添加');
    },
  });

  const deleteRecipientMutation = useMutation({
    mutationFn: (rid: string) => deleteRecipient(surveyId, selectedGroupId!, rid),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['recipients', surveyId, selectedGroupId] });
      queryClient.invalidateQueries({ queryKey: ['sample-groups', surveyId] });
      toast.success('受访者已移除');
    },
  });

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-16 w-full rounded-xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Create Group Form */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex gap-2">
            <Input
              placeholder="新样本组名称 (如: 心理学系大一学生)"
              value={newGroupName}
              onChange={(e) => setNewGroupName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newGroupName.trim()) {
                  createMutation.mutate(newGroupName.trim());
                }
              }}
            />
            <Button
              onClick={() => createMutation.mutate(newGroupName.trim())}
              disabled={!newGroupName.trim() || createMutation.isPending}
            >
              <Plus className="h-4 w-4 mr-1" />
              创建
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Group List */}
      {(!groups || groups.length === 0) ? (
        <Card>
          <CardContent className="py-8 text-center text-muted-foreground">
            <UsersIcon className="mx-auto h-8 w-8 mb-2 opacity-40" />
            <p>尚无样本组，请创建一个</p>
          </CardContent>
        </Card>
      ) : (
        groups.map((group) => (
          <Card key={group.id} className={cn(selectedGroupId === group.id && 'ring-2 ring-blue-200')}>
            <CardContent className="pt-4">
              <div className="flex items-center justify-between">
                <button
                  className="flex items-center gap-2 text-left flex-1"
                  onClick={() =>
                    setSelectedGroupId(
                      selectedGroupId === group.id ? null : group.id,
                    )
                  }
                >
                  <ChevronDown
                    className={cn(
                      'h-4 w-4 transition-transform',
                      selectedGroupId === group.id && 'rotate-180',
                    )}
                  />
                  {editingGroup?.id === group.id ? (
                    <Input
                      className="h-8 w-48"
                      value={editingGroup.name}
                      onChange={(e) =>
                        setEditingGroup({ ...editingGroup, name: e.target.value })
                      }
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          updateMutation.mutate({
                            gid: group.id,
                            name: editingGroup.name,
                          });
                        } else if (e.key === 'Escape') {
                          setEditingGroup(null);
                        }
                      }}
                      autoFocus
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <div>
                      <span className="font-medium">{group.name}</span>
                      {group.description && (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {group.description}
                        </p>
                      )}
                    </div>
                  )}
                </button>
                <div className="flex items-center gap-2">
                  <span className="text-sm text-muted-foreground">
                    {group.recipient_count} 人
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() =>
                      setEditingGroup(editingGroup?.id === group.id ? null : group)
                    }
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (confirm(`确定删除样本组「${group.name}」及所有受访者？`)) {
                        deleteMutation.mutate(group.id);
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-red-500" />
                  </Button>
                </div>
              </div>

              {/* Expanded: Recipients */}
              {selectedGroupId === group.id && (
                <div className="mt-4 pt-4 border-t space-y-3">
                  {/* Quick Add + Import */}
                  <div className="flex gap-2 flex-wrap">
                    <Input
                      placeholder="邮箱"
                      className="w-40 h-8 text-sm"
                      value={newRecipient.email}
                      onChange={(e) =>
                        setNewRecipient({ ...newRecipient, email: e.target.value })
                      }
                    />
                    <Input
                      placeholder="姓名"
                      className="w-32 h-8 text-sm"
                      value={newRecipient.name}
                      onChange={(e) =>
                        setNewRecipient({ ...newRecipient, name: e.target.value })
                      }
                    />
                    <Button
                      size="sm"
                      onClick={() => {
                        if (newRecipient.email || newRecipient.name) {
                          addRecipientMutation.mutate(newRecipient);
                        }
                      }}
                      disabled={
                        (!newRecipient.email && !newRecipient.name) ||
                        addRecipientMutation.isPending
                      }
                    >
                      <UserPlus className="h-3.5 w-3.5 mr-1" />
                      添加
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setImportDialogOpen(true)}
                    >
                      <Upload className="h-3.5 w-3.5 mr-1" />
                      CSV 导入
                    </Button>
                  </div>

                  {/* Recipient Table */}
                  {recipients && recipients.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b text-left">
                            <th className="pb-2 font-medium text-muted-foreground">邮箱/姓名</th>
                            <th className="pb-2 font-medium text-muted-foreground">人口学信息</th>
                            <th className="pb-2 font-medium text-muted-foreground">状态</th>
                            <th className="pb-2 font-medium text-muted-foreground text-right">
                              操作
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {recipients.map((r) => (
                            <tr key={r.id} className="border-b last:border-0">
                              <td className="py-2">
                                <p className="font-medium">{r.name || '-'}</p>
                                <p className="text-xs text-muted-foreground">
                                  {r.email || '-'}
                                </p>
                              </td>
                              <td className="py-2">
                                <div className="flex flex-wrap gap-1">
                                  {Object.entries(r.demographics || {}).map(
                                    ([k, v]) => (
                                      <Badge
                                        key={k}
                                        variant="outline"
                                        className="text-xs"
                                      >
                                        {k}={v}
                                      </Badge>
                                    ),
                                  )}
                                  {!Object.keys(r.demographics || {}).length && (
                                    <span className="text-xs text-muted-foreground">
                                      —
                                    </span>
                                  )}
                                </div>
                              </td>
                              <td className="py-2">
                                <StatusBadge status={r.status} />
                              </td>
                              <td className="py-2 text-right">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() =>
                                    deleteRecipientMutation.mutate(r.id)
                                  }
                                >
                                  <Trash2 className="h-3 w-3 text-red-500" />
                                </Button>
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground py-2">
                      暂无受访者，请手动添加或 CSV 导入
                    </p>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))
      )}

      {/* CSV Import Dialog (simplified: file input inline) */}
      {importDialogOpen && selectedGroupId && (
        <Card className="border-blue-200 bg-blue-50">
          <CardContent className="py-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="font-semibold text-sm">CSV 批量导入</h4>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setImportDialogOpen(false)}
              >
                取消
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mb-2">
              支持 email/邮箱, name/姓名 列，其余列自动归入人口学信息。最多 500 条/次。
            </p>
            <Input
              type="file"
              accept=".csv"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                try {
                  const result = await importRecipientsCSV(
                    surveyId,
                    selectedGroupId,
                    file,
                  );
                  queryClient.invalidateQueries({
                    queryKey: ['recipients', surveyId, selectedGroupId],
                  });
                  queryClient.invalidateQueries({
                    queryKey: ['sample-groups', surveyId],
                  });
                  toast.success(
                    `导入完成: ${result.imported} 条` +
                      (result.errors.length
                        ? `, ${result.errors.length} 条错误`
                        : ''),
                  );
                  if (result.errors.length > 0) {
                    console.warn('CSV import errors:', result.errors);
                  }
                  setImportDialogOpen(false);
                } catch {
                  toast.error('导入失败，请检查文件格式');
                }
              }}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function UsersIcon({ className }: { className?: string }) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  );
}

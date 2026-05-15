import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Share2, Plus, X, Loader2, Copy, Check } from 'lucide-react';
import { toast } from 'sonner';
import {
  getPermissions,
  grantPermission,
  updatePermissionRole,
  revokePermission,
  createInvitation,
  revokeInvitation,
  getInvitations,
  searchUsers,
  type PermissionDetail,
  type InvitationResponse,
  type UserSearchItem,
} from '@/lib/api';
import { useDesignerStore } from '@/features/survey-designer/store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

interface ShareDialogProps {
  surveyId: string;
}

export function ShareDialog({ surveyId }: ShareDialogProps) {
  const isOpen = useDesignerStore((s) => s.isShareDialogOpen);
  const setOpen = useDesignerStore((s) => s.setShareDialogOpen);
  const queryClient = useQueryClient();

  return (
    <Dialog open={isOpen} onOpenChange={setOpen}>
      <DialogContent className="max-h-[80vh] max-w-lg overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Share2 className="h-5 w-5" />
            协作与分享
          </DialogTitle>
          <DialogDescription>
            邀请其他用户协作编辑或查看问卷
          </DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="invite" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="invite">邀请协作者</TabsTrigger>
            <TabsTrigger value="manage">管理权限</TabsTrigger>
          </TabsList>
          <TabsContent value="invite" className="space-y-4 pt-4">
            <InviteTab surveyId={surveyId} />
          </TabsContent>
          <TabsContent value="manage" className="space-y-4 pt-4">
            <ManagePermissionsTab surveyId={surveyId} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}

// ── Invite Tab ─────────────────────────────────────────────────────

function InviteTab({ surveyId }: { surveyId: string }) {
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<'editor' | 'viewer'>('viewer');
  const [copied, setCopied] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const { data: invitations, isLoading: invLoading } = useQuery({
    queryKey: ['surveyInvitations', surveyId],
    queryFn: () => getInvitations(surveyId),
  });

  const sendMutation = useMutation({
    mutationFn: (data: { email: string; role: 'editor' | 'viewer' }) =>
      createInvitation(surveyId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveyInvitations', surveyId] });
      setEmail('');
      toast.success('邀请已创建');
    },
    onError: (err: { detail?: string }) => {
      toast.error(err.detail || '邀请失败');
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (invitationId: string) => revokeInvitation(surveyId, invitationId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveyInvitations', surveyId] });
      toast.success('邀请已撤销');
    },
    onError: () => toast.error('撤销失败'),
  });

  const handleSend = () => {
    if (!email.trim()) {
      toast.error('请输入邮箱');
      return;
    }
    sendMutation.mutate({ email: email.trim(), role });
  };

  const handleCopy = (url: string, id: string) => {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(id);
      setTimeout(() => setCopied(null), 2000);
    });
  };

  const roleLabel = (r: string) => (r === 'editor' ? '编辑者' : '查看者');

  return (
    <div className="space-y-4">
      {/* Send invitation form */}
      <div className="flex items-end gap-2">
        <div className="flex-1">
          <Input
            placeholder="输入邮箱地址..."
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          />
        </div>
        <Select
          value={role}
          onValueChange={(v) => setRole(v as 'editor' | 'viewer')}
        >
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="editor">编辑者</SelectItem>
            <SelectItem value="viewer">查看者</SelectItem>
          </SelectContent>
        </Select>
        <Button
          size="sm"
          onClick={handleSend}
          disabled={sendMutation.isPending}
        >
          {sendMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
        </Button>
      </div>

      {/* Pending invitations list */}
      {invLoading ? (
        <Loader2 className="mx-auto h-5 w-5 animate-spin" />
      ) : invitations && invitations.length > 0 ? (
        <div className="space-y-2">
          <p className="text-xs font-medium text-muted-foreground">
            待处理的邀请 ({invitations.filter((i) => i.status === 'pending').length})
          </p>
          {invitations.map((inv) => (
            <div
              key={inv.id}
              className="flex items-center gap-2 rounded-lg border p-2 text-sm"
            >
              <Badge variant="secondary" className="shrink-0">
                {roleLabel(inv.role)}
              </Badge>
              <span className="min-w-0 flex-1 truncate">{inv.email}</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleCopy(inv.invite_url, inv.id)}
                title="复制邀请链接"
              >
                {copied === inv.id ? (
                  <Check className="h-3 w-3 text-green-600" />
                ) : (
                  <Copy className="h-3 w-3" />
                )}
              </Button>
              {inv.status === 'pending' && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => revokeMutation.mutate(inv.id)}
                  title="撤销邀请"
                >
                  <X className="h-3 w-3 text-destructive" />
                </Button>
              )}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── Manage Permissions Tab ──────────────────────────────────────────

function ManagePermissionsTab({ surveyId }: { surveyId: string }) {
  const queryClient = useQueryClient();

  const { data: permissions, isLoading } = useQuery({
    queryKey: ['surveyPermissions', surveyId],
    queryFn: () => getPermissions(surveyId),
  });

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<UserSearchItem[]>([]);
  const [isSearching, setIsSearching] = useState(false);

  const updateRoleMutation = useMutation({
    mutationFn: (args: { permId: string; role: 'editor' | 'viewer' }) =>
      updatePermissionRole(surveyId, args.permId, { role: args.role }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveyPermissions', surveyId] });
      toast.success('角色已更新');
    },
    onError: () => toast.error('更新失败'),
  });

  const revokeMutation = useMutation({
    mutationFn: (permId: string) => revokePermission(surveyId, permId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveyPermissions', surveyId] });
      toast.success('权限已移除');
    },
    onError: () => toast.error('移除失败'),
  });

  const grantMutation = useMutation({
    mutationFn: (userId: string) =>
      grantPermission(surveyId, { user_id: userId, role: 'viewer' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['surveyPermissions', surveyId] });
      setSearchResults([]);
      setSearchQuery('');
      toast.success('协作者已添加');
    },
    onError: (err: { detail?: string }) => {
      toast.error(err.detail || '添加失败');
    },
  });

  const handleSearch = async (q: string) => {
    setSearchQuery(q);
    if (q.length < 2) {
      setSearchResults([]);
      return;
    }
    setIsSearching(true);
    try {
      const results = await searchUsers(q);
      setSearchResults(results);
    } catch {
      // ignore
    } finally {
      setIsSearching(false);
    }
  };

  const roleLabel = (r: string) => {
    const map: Record<string, string> = {
      owner: '所有者',
      editor: '编辑者',
      viewer: '查看者',
    };
    return map[r] || r;
  };

  return (
    <div className="space-y-4">
      {/* Search and add users */}
      <div className="space-y-2">
        <Input
          placeholder="搜索用户（输入邮箱前缀）..."
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
        />
        {isSearching && (
          <Loader2 className="mx-auto h-4 w-4 animate-spin" />
        )}
        {searchResults.length > 0 && (
          <div className="rounded-lg border p-2 space-y-1 max-h-40 overflow-y-auto">
            {searchResults.map((u) => (
              <div
                key={u.id}
                className="flex items-center justify-between rounded p-1 hover:bg-muted"
              >
                <div>
                  <span className="text-sm font-medium">{u.display_name}</span>
                  <span className="ml-2 text-xs text-muted-foreground">
                    {u.email}
                  </span>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => grantMutation.mutate(u.id)}
                  disabled={grantMutation.isPending}
                >
                  <Plus className="mr-1 h-3 w-3" />
                  添加
                </Button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Permissions list */}
      {isLoading ? (
        <Loader2 className="mx-auto h-5 w-5 animate-spin" />
      ) : !permissions || permissions.length === 0 ? (
        <p className="text-sm text-muted-foreground">暂无协作者</p>
      ) : (
        <div className="space-y-2">
          {permissions.map((perm) => (
            <div
              key={perm.id}
              className="flex items-center gap-2 rounded-lg border p-2 text-sm"
            >
              <div className="min-w-0 flex-1">
                <p className="font-medium truncate">{perm.user_display_name}</p>
                <p className="text-xs text-muted-foreground truncate">
                  {perm.user_email}
                </p>
              </div>
              {perm.role === 'owner' ? (
                <Badge>{roleLabel(perm.role)}</Badge>
              ) : (
                <>
                  <Select
                    value={perm.role}
                    onValueChange={(v) =>
                      updateRoleMutation.mutate({
                        permId: perm.id,
                        role: v as 'editor' | 'viewer',
                      })
                    }
                  >
                    <SelectTrigger className="w-24 h-7 text-xs">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="editor">编辑者</SelectItem>
                      <SelectItem value="viewer">查看者</SelectItem>
                    </SelectContent>
                  </Select>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      if (confirm(`确定要移除 ${perm.user_display_name} 吗？`)) {
                        revokeMutation.mutate(perm.id);
                      }
                    }}
                  >
                    <X className="h-3 w-3 text-destructive" />
                  </Button>
                </>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

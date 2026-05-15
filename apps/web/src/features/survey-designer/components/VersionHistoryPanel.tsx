import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Clock, RotateCcw, Loader2, ChevronDown, ChevronUp } from 'lucide-react';
import { toast } from 'sonner';
import {
  getVersions,
  getVersionDetail,
  restoreVersion,
  diffVersions,
  type VersionListItem,
  type VersionDetail,
  type VersionDiffResponse,
} from '@/lib/api';
import { useDesignerStore } from '@/features/survey-designer/store';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/components/ui/dialog';

interface VersionHistoryPanelProps {
  surveyId: string;
}

export function VersionHistoryPanel({ surveyId }: VersionHistoryPanelProps) {
  const [selectedVersion, setSelectedVersion] = useState<VersionDetail | null>(null);
  const [diffFrom, setDiffFrom] = useState<string | null>(null);
  const [diffTo, setDiffTo] = useState<string | null>(null);
  const [diffResult, setDiffResult] = useState<string | null>(null);
  const [showDiff, setShowDiff] = useState(false);
  const queryClient = useQueryClient();

  const isOpen = useDesignerStore((s) => s.isVersionPanelOpen);
  const setOpen = useDesignerStore((s) => s.setVersionPanelOpen);

  const { data: versions, isLoading } = useQuery({
    queryKey: ['surveyVersions', surveyId],
    queryFn: () => getVersions(surveyId),
    enabled: isOpen,
  });

  const restoreMutation = useMutation({
    mutationFn: (versionId: string) =>
      restoreVersion(surveyId, versionId, `Restored from version history`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['survey', surveyId] });
      queryClient.invalidateQueries({ queryKey: ['surveyVersions', surveyId] });
      toast.success('版本已恢复，页面即将刷新');
      // Reload so SurveyJS gets the restored content
      setTimeout(() => window.location.reload(), 800);
    },
    onError: () => toast.error('恢复失败'),
  });

  const handleView = async (versionId: string) => {
    try {
      const detail = await getVersionDetail(surveyId, versionId);
      setSelectedVersion(detail);
    } catch {
      toast.error('加载版本详情失败');
    }
  };

  const handleDiffSelect = (versionId: string) => {
    if (!diffFrom) {
      setDiffFrom(versionId);
    } else if (versionId !== diffFrom) {
      setDiffTo(versionId);
    }
  };

  const handleRunDiff = async () => {
    if (!diffFrom || !diffTo) return;
    try {
      const result = await diffVersions(surveyId, diffFrom, diffTo);
      setDiffResult(result.diff_text);
      setShowDiff(true);
    } catch {
      toast.error('对比失败');
    }
  };

  const handleRestore = async (versionId: string) => {
    if (confirm('确定要恢复到此版本吗？当前内容将被保存为新版本。')) {
      restoreMutation.mutate(versionId);
    }
  };

  const resetDiffState = () => {
    setDiffFrom(null);
    setDiffTo(null);
    setDiffResult(null);
    setShowDiff(false);
  };

  return (
    <Dialog open={isOpen} onOpenChange={setOpen}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Clock className="h-5 w-5" />
            版本历史
          </DialogTitle>
          <DialogDescription>
            查看和恢复问卷的历史版本。恢复操作会先保存当前版本。
          </DialogDescription>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        ) : !versions || versions.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            暂无版本记录。每次保存后会自动创建版本快照。
          </p>
        ) : (
          <div className="space-y-4">
            {/* Version list */}
            <div className="space-y-2">
              {versions.map((v) => (
                <VersionRow
                  key={v.id}
                  version={v}
                  isSelected={
                    diffFrom === v.id || diffTo === v.id
                  }
                  onView={() => handleView(v.id)}
                  onRestore={() => handleRestore(v.id)}
                  onDiffSelect={() => handleDiffSelect(v.id)}
                  isRestoring={restoreMutation.isPending}
                />
              ))}
            </div>

            {/* Diff controls */}
            {diffFrom && (
              <div className="rounded-lg border p-3 space-y-2">
                <p className="text-xs text-muted-foreground">
                  {diffTo
                    ? '已选择两个版本，点击对比查看差异'
                    : '已选择起始版本，再点击另一个版本以完成选择'}
                </p>
                <div className="flex gap-2">
                  {diffFrom && diffTo && (
                    <Button size="sm" onClick={handleRunDiff}>
                      对比差异
                    </Button>
                  )}
                  <Button size="sm" variant="outline" onClick={resetDiffState}>
                    取消
                  </Button>
                </div>
              </div>
            )}

            {/* Diff result */}
            {showDiff && diffResult && (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="text-sm font-medium">差异对比</h4>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setShowDiff((s) => !s)}
                  >
                    {showDiff ? (
                      <ChevronUp className="h-4 w-4" />
                    ) : (
                      <ChevronDown className="h-4 w-4" />
                    )}
                  </Button>
                </div>
                <pre className="max-h-64 overflow-auto rounded bg-muted p-3 text-xs font-mono whitespace-pre-wrap">
                  {diffResult}
                </pre>
              </div>
            )}

            {/* Version detail */}
            {selectedVersion && (
              <div className="rounded-lg border p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-medium">
                    v{selectedVersion.version} — {selectedVersion.title}
                  </h4>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setSelectedVersion(null)}
                  >
                    关闭
                  </Button>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                  <p>创建者: {selectedVersion.creator_name || '已删除用户'}</p>
                  <p>时间: {new Date(selectedVersion.created_at).toLocaleString()}</p>
                  {selectedVersion.changelog && (
                    <p>说明: {selectedVersion.changelog}</p>
                  )}
                </div>
                <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-xs">
                  {JSON.stringify(selectedVersion.json_content, null, 2)}
                </pre>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => handleRestore(selectedVersion.id)}
                  disabled={restoreMutation.isPending}
                >
                  {restoreMutation.isPending ? (
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                  ) : (
                    <RotateCcw className="mr-1 h-3 w-3" />
                  )}
                  恢复此版本
                </Button>
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function VersionRow({
  version,
  isSelected,
  onView,
  onRestore,
  onDiffSelect,
  isRestoring,
}: {
  version: VersionListItem;
  isSelected: boolean;
  onView: () => void;
  onRestore: () => void;
  onDiffSelect: () => void;
  isRestoring: boolean;
}) {
  return (
    <div
      className={`flex items-center gap-3 rounded-lg border p-3 text-sm ${
        isSelected ? 'border-primary bg-primary/5' : ''
      }`}
    >
      <Badge variant="secondary" className="shrink-0">
        v{version.version}
      </Badge>
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{version.title}</p>
        <p className="text-xs text-muted-foreground">
          {version.creator_name || '已删除用户'} ·{' '}
          {new Date(version.created_at).toLocaleString()}
        </p>
      </div>
      <Button variant="ghost" size="sm" onClick={onView}>
        查看
      </Button>
      <Button variant="ghost" size="sm" onClick={onDiffSelect}>
        对比
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={onRestore}
        disabled={isRestoring}
      >
        <RotateCcw className="mr-1 h-3 w-3" />
        恢复
      </Button>
    </div>
  );
}

import { useQueryClient } from '@tanstack/react-query';
import { AlertTriangle } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { useDesignerStore } from '@/features/survey-designer/store';

interface ConflictDialogProps {
  surveyId: string;
}

export function ConflictDialog({ surveyId }: ConflictDialogProps) {
  const isOpen = useDesignerStore((s) => s.isConflictDialogOpen);
  const setOpen = useDesignerStore((s) => s.setConflictDialogOpen);
  const conflictInfo = useDesignerStore((s) => s.conflictInfo);
  const setConflictInfo = useDesignerStore((s) => s.setConflictInfo);
  const queryClient = useQueryClient();

  const handleRefresh = () => {
    // Reload the survey from server
    queryClient.invalidateQueries({ queryKey: ['survey', surveyId] });
    setOpen(false);
    setConflictInfo(null);
    window.location.reload();
  };

  const handleCancel = () => {
    setOpen(false);
    setConflictInfo(null);
  };

  return (
    <AlertDialog open={isOpen} onOpenChange={setOpen}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-amber-500" />
            检测到版本冲突
          </AlertDialogTitle>
          <AlertDialogDescription>
            问卷已被其他用户修改（版本从 v{conflictInfo?.expectedVersion} 变为
            v{conflictInfo?.serverVersion}）。你的修改未保存。
            <br />
            <br />
            建议：放弃当前修改并刷新页面以获取最新版本。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel onClick={handleCancel}>取消</AlertDialogCancel>
          <AlertDialogAction onClick={handleRefresh}>
            放弃我的修改并刷新
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { ScaleResponse } from '@/lib/api';
import { importScaleToSurvey } from '@/lib/api';
import { toast } from 'sonner';

interface Props {
  scale: ScaleResponse | null;
  surveyId: string;
  surveyTitle?: string;
  onClose: () => void;
  onSuccess?: () => void;
}

export function ScaleImportDialog({ scale, surveyId, surveyTitle, onClose, onSuccess }: Props) {
  const navigate = useNavigate();
  const [position, setPosition] = useState('end');

  const importMutation = useMutation({
    mutationFn: () => importScaleToSurvey(scale!.id, surveyId, position),
    onSuccess: (data) => {
      toast.success(`已导入 ${data.items_added} 个题项`);
      onSuccess?.();
      navigate(`/survey/${surveyId}`);
    },
    onError: () => {
      toast.error('导入失败');
    },
  });

  if (!scale) return null;

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={onClose}>
      <Card className="w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
        <CardHeader>
          <CardTitle className="text-lg">导入题项到问卷</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="text-sm space-y-1">
            <p><span className="text-muted-foreground">量表：</span>{scale.name}</p>
            <p><span className="text-muted-foreground">题项数：</span>{scale.items?.length || 0}</p>
            {surveyTitle && <p><span className="text-muted-foreground">目标问卷：</span>{surveyTitle}</p>}
          </div>

          <div>
            <p className="text-sm text-muted-foreground mb-2">插入位置</p>
            <div className="flex gap-2">
              {[
                { value: 'start', label: '问卷开头' },
                { value: 'end', label: '问卷末尾' },
              ].map((opt) => (
                <Button
                  key={opt.value}
                  variant={position === opt.value ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setPosition(opt.value)}
                >
                  {opt.label}
                </Button>
              ))}
            </div>
          </div>

          <div className="flex gap-2 justify-end">
            <Button variant="outline" onClick={onClose}>取消</Button>
            <Button onClick={() => importMutation.mutate()} disabled={importMutation.isPending}>
              {importMutation.isPending ? '导入中...' : '确认导入'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Trash2, ExternalLink, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { getSavedReferences, deleteReference, type SavedReferenceResponse } from '@/lib/api';
import { toast } from 'sonner';

export function SavedReferencesList() {
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({
    queryKey: ['saved-references'],
    queryFn: () => getSavedReferences({ limit: 50 }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteReference,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['saved-references'] });
      toast.success('已删除');
    },
    onError: () => toast.error('删除失败'),
  });

  if (isLoading) return <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />;
  if (error) return <p className="text-destructive text-sm">加载失败</p>;
  if (!data?.items.length) return <p className="text-muted-foreground text-sm py-6 text-center">暂无已保存的文献</p>;

  return (
    <div className="space-y-2">
      {data.items.map((ref: SavedReferenceResponse) => (
        <div key={ref.id} className="flex items-start justify-between gap-2 p-3 rounded border hover:bg-muted/50 transition-colors">
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{ref.title}</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {ref.authors?.slice(0, 2).join(', ')}{(ref.authors?.length || 0) > 2 ? ' et al.' : ''}
              {ref.year && ` · ${ref.year}`}
              {ref.journal && ` · ${ref.journal}`}
            </p>
          </div>
          <div className="flex gap-1 shrink-0">
            {ref.url && (
              <a href={ref.url} target="_blank" rel="noopener noreferrer">
                <Button variant="ghost" size="icon" className="h-7 w-7"><ExternalLink className="h-3 w-3" /></Button>
              </a>
            )}
            <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive"
              onClick={() => deleteMutation.mutate(ref.id)}>
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
      ))}
      <p className="text-xs text-muted-foreground text-center pt-1">共 {data.total} 条</p>
    </div>
  );
}

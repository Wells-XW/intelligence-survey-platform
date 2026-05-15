import { Ruler } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { SplitHalfResult } from '@/lib/api';

interface Props {
  data: SplitHalfResult | null;
  isLoading?: boolean;
}

export function SplitHalfDisplay({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>分半信度</CardTitle></CardHeader>
        <CardContent><p className="text-muted-foreground">计算中…</p></CardContent>
      </Card>
    );
  }

  if (!data || data.error) {
    return (
      <Card>
        <CardHeader><CardTitle>分半信度</CardTitle></CardHeader>
        <CardContent>
          <p className="text-muted-foreground">
            {data?.error === 'too_few_items'
              ? '需要至少 2 个题项'
              : data?.error === 'insufficient_data'
                ? '有效样本量不足'
                : '暂无数据'}
          </p>
        </CardContent>
      </Card>
    );
  }

  const getColor = (v: number | null) => {
    if (v === null) return 'text-muted-foreground';
    if (v >= 0.8) return 'text-green-600';
    if (v >= 0.7) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Ruler className="h-5 w-5" />
          分半信度
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          方法: {data.method === 'odd_even' ? '奇偶分半' : '前后分半'} | N = {data.n_valid}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-4">
          <div className="text-center">
            <p className="text-xs text-muted-foreground">Spearman-Brown</p>
            <p className={`text-3xl font-bold ${getColor(data.spearman_brown)}`}>
              {data.spearman_brown !== null ? data.spearman_brown.toFixed(3) : 'N/A'}
            </p>
          </div>
          <div className="text-center">
            <p className="text-xs text-muted-foreground">分半相关系数 r</p>
            <p className={`text-2xl font-semibold ${getColor(data.split_half_r)}`}>
              {data.split_half_r !== null ? data.split_half_r.toFixed(3) : 'N/A'}
            </p>
          </div>
        </div>
        <div className="bg-muted rounded p-2 text-sm">
          <span className="font-medium">解读：</span>
          {data.interpretation}
        </div>
        <div className="text-xs text-muted-foreground">
          <p>前半: {data.half1_items.join(', ') || '—'}</p>
          <p>后半: {data.half2_items.join(', ') || '—'}</p>
        </div>
      </CardContent>
    </Card>
  );
}

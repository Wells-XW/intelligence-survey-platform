import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ItemTotalCorrelationResult } from '@/lib/api';

interface Props {
  data: ItemTotalCorrelationResult | null;
  isLoading?: boolean;
}

const FLAG_MAP: Record<string, { label: string; className: string }> = {
  good: { label: '良好', className: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
  moderate: { label: '一般', className: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400' },
  weak: { label: '弱', className: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400' },
};

export function ItemTotalTable({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>题总相关</CardTitle></CardHeader>
        <CardContent><p className="text-muted-foreground">计算中…</p></CardContent>
      </Card>
    );
  }

  if (!data || data.error) {
    return (
      <Card>
        <CardHeader><CardTitle>题总相关</CardTitle></CardHeader>
        <CardContent>
          <p className="text-muted-foreground">
            {data?.error || '暂无数据'}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>题项—总相关</CardTitle>
        <p className="text-xs text-muted-foreground">有效回答数: {data.n_valid}</p>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>题项</TableHead>
              <TableHead className="text-right">题总相关 (r)</TableHead>
              <TableHead className="text-right">删除后 α</TableHead>
              <TableHead className="text-center">质量</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((item) => {
              const flag = FLAG_MAP[item.flag] || FLAG_MAP.weak;
              const rColor =
                item.corrected_item_total_r >= 0.4
                  ? 'text-green-600'
                  : item.corrected_item_total_r >= 0.2
                    ? 'text-yellow-600'
                    : 'text-red-600';
              return (
                <TableRow key={item.item_name}>
                  <TableCell className="font-mono text-xs">{item.item_name}</TableCell>
                  <TableCell className={`text-right font-mono ${rColor}`}>
                    {item.corrected_item_total_r.toFixed(3)}
                  </TableCell>
                  <TableCell className="text-right font-mono">
                    {item.alpha_if_deleted !== null
                      ? item.alpha_if_deleted.toFixed(3)
                      : '—'}
                  </TableCell>
                  <TableCell className="text-center">
                    <span className={`inline-block px-2 py-0.5 rounded text-xs ${flag.className}`}>
                      {flag.label}
                    </span>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

import { ExternalLink } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ReliabilityNormComparisonResult } from '@/lib/api';

interface Props {
  data: ReliabilityNormComparisonResult | null;
  isLoading?: boolean;
}

export function ReliabilityComparison({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>常模比较</CardTitle></CardHeader>
        <CardContent><p className="text-muted-foreground">计算中…</p></CardContent>
      </Card>
    );
  }

  if (!data) {
    return (
      <Card>
        <CardHeader><CardTitle>常模比较</CardTitle></CardHeader>
        <CardContent>
          <p className="text-muted-foreground">
            选择题项后点击「比较常模」，将实测信度与量表库中已发表常模对比。
          </p>
        </CardContent>
      </Card>
    );
  }

  const diffColor = (diff: number) => {
    const abs = Math.abs(diff);
    if (abs < 0.05) return 'text-green-600';
    if (abs < 0.10) return 'text-yellow-600';
    return 'text-red-600';
  };

  return (
    <div className="space-y-4">
      {/* Summary card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">实测信度</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div className="bg-muted rounded p-3">
              <p className="text-xs text-muted-foreground">Cronbach's α</p>
              <p className="text-2xl font-bold font-mono">
                {data.observed_alpha.toFixed(3)}
              </p>
            </div>
            <div className="bg-muted rounded p-3">
              <p className="text-xs text-muted-foreground">题项数</p>
              <p className="text-2xl font-bold font-mono">{data.n_items}</p>
            </div>
            <div className="bg-muted rounded p-3">
              <p className="text-xs text-muted-foreground">有效 N</p>
              <p className="text-2xl font-bold font-mono">{data.n_valid}</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary text */}
      <div className="bg-muted rounded p-3 text-sm">{data.summary}</div>

      {/* Comparison table */}
      {data.comparison_scales.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              已发表常模对比 ({data.comparison_scales.length} 个匹配)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>量表名称</TableHead>
                  <TableHead className="text-right">已发表 α</TableHead>
                  <TableHead className="text-right">实测 α</TableHead>
                  <TableHead className="text-right">差值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.comparison_scales.map((entry) => (
                  <TableRow key={entry.scale_id}>
                    <TableCell className="text-xs max-w-[200px] truncate">
                      {entry.scale_name}
                      {entry.citation && (
                        <span className="block text-muted-foreground truncate">
                          {entry.citation}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {entry.published_alpha.toFixed(3)}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {entry.observed_alpha.toFixed(3)}
                    </TableCell>
                    <TableCell
                      className={`text-right font-mono text-xs font-medium ${diffColor(entry.difference)}`}
                    >
                      {entry.difference > 0 ? '+' : ''}{entry.difference.toFixed(3)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

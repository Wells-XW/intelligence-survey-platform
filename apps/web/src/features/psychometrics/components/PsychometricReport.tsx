import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { PsychometricReportResponse } from '@/lib/api';

interface Props {
  data: PsychometricReportResponse | null;
  isLoading?: boolean;
}

export function PsychometricReport({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-center text-muted-foreground">生成报告中…</p>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.sections.length === 0) {
    return (
      <Card>
        <CardContent className="py-8">
          <p className="text-center text-muted-foreground">
            选择题项后点击「生成报告」获取 APA 格式心理计量学报告
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {data.sections.map((section, idx) => (
        <Card key={idx}>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">
              {idx + 1}. {section.title}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {section.type === 'text' && (
              <p className="text-sm leading-relaxed text-muted-foreground">
                {(section.content as { text: string }).text}
              </p>
            )}

            {section.type === 'metric_card' && (
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(section.content as Record<string, unknown>).map(([key, val]) => {
                  if (typeof val === 'boolean' || typeof val === 'number' || typeof val === 'string') {
                    return (
                      <div key={key} className="bg-muted rounded p-3">
                        <p className="text-xs text-muted-foreground">{key}</p>
                        <p className="text-lg font-bold font-mono">
                          {typeof val === 'number' ? val.toFixed(3) : String(val)}
                        </p>
                      </div>
                    );
                  }
                  return null;
                })}
              </div>
            )}

            {section.type === 'table' && (
              <Table>
                <TableHeader>
                  <TableRow>
                    {((section.content as { headers: string[] }).headers || []).map((h: string) => (
                      <TableHead key={h}>{h}</TableHead>
                    ))}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {((section.content as { rows: string[][] }).rows || []).map((row, ri) => (
                    <TableRow key={ri}>
                      {row.map((cell, ci) => (
                        <TableCell key={ci}>{cell}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}

            {section.type === 'comparison_table' && (
              <p className="text-sm text-muted-foreground">
                构念间相关矩阵已生成，请切换到「构念构建」标签查看详情。
              </p>
            )}
          </CardContent>
        </Card>
      ))}
      <p className="text-xs text-muted-foreground text-right">
        报告生成时间: {new Date(data.generated_at).toLocaleString('zh-CN')}
      </p>
    </div>
  );
}

interface ResponseDataTableProps {
  responses: Array<{
    id: string;
    respondent_id?: string | null;
    is_complete: boolean;
    completion_time_seconds?: number | null;
    submitted_at: string;
  }>;
}

export function ResponseDataTable({ responses }: ResponseDataTableProps) {
  if (responses.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-muted-foreground">
        暂无回复数据
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-muted/50">
            <th className="px-4 py-2 text-left font-medium">回复 ID</th>
            <th className="px-4 py-2 text-left font-medium">受访者</th>
            <th className="px-4 py-2 text-left font-medium">完成状态</th>
            <th className="px-4 py-2 text-left font-medium">用时(秒)</th>
            <th className="px-4 py-2 text-left font-medium">提交时间</th>
          </tr>
        </thead>
        <tbody>
          {responses.map((r, i) => (
            <tr
              key={r.id}
              className={`border-b border-border ${
                i % 2 === 0 ? 'bg-white' : 'bg-muted/20'
              }`}
            >
              <td className="px-4 py-2 font-mono text-xs">{r.id.slice(0, 8)}</td>
              <td className="px-4 py-2 text-muted-foreground">
                {r.respondent_id || '匿名'}
              </td>
              <td className="px-4 py-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                    r.is_complete
                      ? 'bg-green-100 text-green-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}
                >
                  {r.is_complete ? '完成' : '未完成'}
                </span>
              </td>
              <td className="px-4 py-2 tabular-nums">
                {r.completion_time_seconds != null
                  ? `${r.completion_time_seconds}s`
                  : '-'}
              </td>
              <td className="px-4 py-2 text-muted-foreground">
                {new Date(r.submitted_at).toLocaleString('zh-CN')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

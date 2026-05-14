import type { SqpQualitySummary } from '@/lib/api';

const QUALITY_COLORS: Record<string, string> = {
  ready: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  'needs-revision': 'bg-amber-50 border-amber-200 text-amber-800',
  'needs-redesign': 'bg-red-50 border-red-200 text-red-800',
};

const QUALITY_LABELS: Record<string, string> = {
  ready: '可直接使用',
  'needs-revision': '需要修订',
  'needs-redesign': '需要重设计',
};

const ALPHA_COLORS: Record<string, string> = {
  excellent: 'text-emerald-600',
  good: 'text-emerald-600',
  acceptable: 'text-amber-600',
  questionable: 'text-orange-600',
  poor: 'text-red-600',
};

function interpretAlpha(alpha: number): { label: string; color: string } {
  if (alpha >= 0.9) return { label: 'Excellent', color: 'text-emerald-600' };
  if (alpha >= 0.8) return { label: 'Good', color: 'text-emerald-600' };
  if (alpha >= 0.7) return { label: 'Acceptable', color: 'text-amber-600' };
  if (alpha >= 0.6) return { label: 'Questionable', color: 'text-orange-600' };
  return { label: 'Poor', color: 'text-red-600' };
}

interface Props {
  report: SqpQualitySummary;
}

export function SqpReportCard({ report }: Props) {
  const alpha = interpretAlpha(report.estimated_cronbach_alpha);
  const colorClass = QUALITY_COLORS[report.recommendation] || 'bg-gray-50 border-gray-200';

  return (
    <div className={`rounded-lg border p-5 ${colorClass}`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-sm">SQP 质量评估</h3>
        <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-background/60">
          {QUALITY_LABELS[report.recommendation] || report.recommendation}
        </span>
      </div>

      {/* Quality Score */}
      <div className="flex items-end gap-2 mb-4">
        <span className="text-3xl font-bold tabular-nums">
          {(report.overall_quality * 100).toFixed(0)}
        </span>
        <span className="text-sm text-muted-foreground mb-1">/ 100</span>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <span className="text-muted-foreground">题项数</span>
          <p className="font-semibold">{report.total_items}</p>
        </div>
        <div>
          <span className="text-muted-foreground">风险标志</span>
          <p className={`font-semibold ${report.total_flags > 0 ? 'text-amber-600' : 'text-emerald-600'}`}>
            {report.total_flags}
          </p>
        </div>
        <div className="col-span-2">
          <span className="text-muted-foreground">预估 Cronbach's α</span>
          <p className={`font-semibold ${alpha.color}`}>
            {report.estimated_cronbach_alpha.toFixed(3)} ({alpha.label})
          </p>
        </div>
      </div>

      {/* Summary */}
      {report.summary && (
        <p className="text-xs mt-3 opacity-80">{report.summary}</p>
      )}
    </div>
  );
}

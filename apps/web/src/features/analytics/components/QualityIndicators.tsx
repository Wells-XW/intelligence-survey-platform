import { Card, CardContent } from '@/components/ui/card';
import {
  Clock,
  CheckCircle,
  Zap,
  AlignJustify,
  Eye,
  AlertTriangle,
} from 'lucide-react';

interface QualityIndicatorsProps {
  completionRate: number;
  avgCompletionSeconds: number;
  medianCompletionSeconds: number;
  speederCount: number;
  speederThreshold: number;
  straightlinerCount: number;
  totalResponses: number;
  completeResponses: number;
  // T9 extended
  inconsistencyRate?: number | null;
  inconsistentRespondents?: number | null;
  attentionCheckPassRate?: number | null;
}

export function QualityIndicators(props: QualityIndicatorsProps) {
  const indicators = [
    {
      icon: CheckCircle,
      label: '完成率',
      value: `${props.completionRate}%`,
      sub: `${props.completeResponses} / ${props.totalResponses} 份`,
      color: props.completionRate >= 80 ? 'text-green-600' : 'text-yellow-600',
    },
    {
      icon: Clock,
      label: '中位用时',
      value: `${props.medianCompletionSeconds}s`,
      sub: `平均 ${props.avgCompletionSeconds}s`,
      color: 'text-blue-600',
    },
    {
      icon: Zap,
      label: '快速填答者',
      value: `${props.speederCount}`,
      sub: `阈值 < ${props.speederThreshold}s`,
      color: props.speederCount > 0 ? 'text-orange-600' : 'text-green-600',
    },
    {
      icon: AlignJustify,
      label: '直线填答者',
      value: `${props.straightlinerCount}`,
      sub: '≥80% 相同答案',
      color: props.straightlinerCount > 0 ? 'text-red-600' : 'text-green-600',
    },
    {
      icon: AlertTriangle,
      label: '不一致应答',
      value:
        props.inconsistentRespondents != null
          ? `${props.inconsistentRespondents}`
          : '—',
      sub:
        props.inconsistencyRate != null
          ? `${(props.inconsistencyRate * 100).toFixed(1)}%`
          : '无反向题',
      color:
        (props.inconsistencyRate ?? 0) > 0.05
          ? 'text-red-600'
          : 'text-green-600',
    },
    {
      icon: Eye,
      label: '注意力检测通过率',
      value:
        props.attentionCheckPassRate != null
          ? `${props.attentionCheckPassRate}%`
          : '—',
      sub: '无注意力检测题',
      color:
        (props.attentionCheckPassRate ?? 100) >= 90
          ? 'text-green-600'
          : 'text-red-600',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      {indicators.map((ind) => (
        <Card key={ind.label}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <ind.icon className={`h-5 w-5 ${ind.color}`} />
              <span className="text-xs text-muted-foreground">{ind.label}</span>
            </div>
            <p
              className={`mt-2 text-xl font-semibold tabular-nums ${ind.color}`}
            >
              {ind.value}
            </p>
            <p className="text-xs text-muted-foreground">{ind.sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

import { Card, CardContent } from '@/components/ui/card';
import { Clock, CheckCircle, Zap, AlignJustify } from 'lucide-react';

interface QualityIndicatorsProps {
  completionRate: number;
  avgCompletionSeconds: number;
  medianCompletionSeconds: number;
  speederCount: number;
  speederThreshold: number;
  straightlinerCount: number;
  totalResponses: number;
  completeResponses: number;
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
      sub: `阈值 &lt; ${props.speederThreshold}s`,
      color: props.speederCount > 0 ? 'text-orange-600' : 'text-green-600',
    },
    {
      icon: AlignJustify,
      label: '直线填答者',
      value: `${props.straightlinerCount}`,
      sub: '≥80% 相同答案',
      color: props.straightlinerCount > 0 ? 'text-red-600' : 'text-green-600',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {indicators.map((ind) => (
        <Card key={ind.label}>
          <CardContent className="p-4">
            <div className="flex items-center gap-2">
              <ind.icon className={`h-5 w-5 ${ind.color}`} />
              <span className="text-xs text-muted-foreground">{ind.label}</span>
            </div>
            <p className={`mt-2 text-xl font-semibold tabular-nums ${ind.color}`}>
              {ind.value}
            </p>
            <p className="text-xs text-muted-foreground">{ind.sub}</p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

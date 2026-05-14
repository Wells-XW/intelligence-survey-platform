import { Card, CardContent } from '@/components/ui/card';
import { ShieldCheck, ShieldAlert, ShieldX } from 'lucide-react';

interface CronbachDisplayProps {
  scaleName: string;
  items: string[];
  alpha: number;
  interpretation: string;
  nValidResponses: number;
}

function getAlphaColor(alpha: number): string {
  if (alpha >= 0.8) return 'text-green-600';
  if (alpha >= 0.7) return 'text-blue-600';
  if (alpha >= 0.6) return 'text-yellow-600';
  return 'text-red-600';
}

function getAlphaIcon(alpha: number) {
  if (alpha >= 0.8) return ShieldCheck;
  if (alpha >= 0.6) return ShieldAlert;
  return ShieldX;
}

export function CronbachDisplay({
  scaleName,
  items,
  alpha,
  interpretation,
  nValidResponses,
}: CronbachDisplayProps) {
  const Icon = getAlphaIcon(alpha);
  const colorClass = getAlphaColor(alpha);

  return (
    <Card>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <h4 className="font-medium text-gray-900">{scaleName}</h4>
            <p className="mt-1 text-xs text-muted-foreground">
              {items.length} 题 · {nValidResponses} 份有效回复
            </p>
            <p className="mt-3 flex items-baseline gap-2">
              <span className={`text-3xl font-bold tabular-nums ${colorClass}`}>
                {alpha.toFixed(3)}
              </span>
              <span className="text-xs text-muted-foreground">Cronbach's α</span>
            </p>
            <p className={`mt-1 text-xs ${colorClass}`}>{interpretation}</p>
          </div>
          <Icon className={`h-8 w-8 ${colorClass}`} />
        </div>
        <div className="mt-3 flex flex-wrap gap-1">
          {items.map((item) => (
            <span
              key={item}
              className="rounded bg-muted px-2 py-0.5 text-xs font-mono text-muted-foreground"
            >
              {item}
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

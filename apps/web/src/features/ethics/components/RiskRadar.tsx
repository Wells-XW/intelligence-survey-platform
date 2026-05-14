import { Card, CardContent } from '@/components/ui/card';
import { Shield, ShieldAlert, ShieldCheck, ShieldX } from 'lucide-react';

interface RiskRadarProps {
  riskScore: number;
  riskLevel: string;
  itemsChecked: number;
  itemsPassed: number;
  itemsWarning: number;
  itemsFailed: number;
}

const riskConfig: Record<string, { color: string; bg: string; icon: typeof Shield; label: string }> = {
  low: {
    color: 'text-green-600',
    bg: 'bg-green-50',
    icon: ShieldCheck,
    label: '低风险',
  },
  medium: {
    color: 'text-yellow-600',
    bg: 'bg-yellow-50',
    icon: Shield,
    label: '中风险',
  },
  high: {
    color: 'text-orange-600',
    bg: 'bg-orange-50',
    icon: ShieldAlert,
    label: '高风险',
  },
  critical: {
    color: 'text-red-600',
    bg: 'bg-red-50',
    icon: ShieldX,
    label: '严重风险',
  },
};

export function RiskRadar({
  riskScore,
  riskLevel,
  itemsChecked,
  itemsPassed,
  itemsWarning,
  itemsFailed,
}: RiskRadarProps) {
  const config = riskConfig[riskLevel] || riskConfig.medium;
  const Icon = config.icon;

  // Gauge fill (0-100)
  const gaugeColor =
    riskScore <= 20 ? 'stroke-green-500' :
    riskScore <= 40 ? 'stroke-yellow-500' :
    riskScore <= 60 ? 'stroke-orange-500' :
    'stroke-red-500';

  const circumference = 2 * Math.PI * 40; // r=40
  const offset = circumference - (Math.min(riskScore, 100) / 100) * circumference;

  return (
    <Card className={config.bg}>
      <CardContent className="p-6">
        <div className="flex flex-col items-center gap-4 sm:flex-row">
          {/* Gauge */}
          <div className="relative h-28 w-28 flex-shrink-0">
            <svg viewBox="0 0 100 100" className="h-full w-full -rotate-90">
              <circle cx="50" cy="50" r="40" fill="none" stroke="currentColor"
                className="text-muted/20" strokeWidth="10" />
              <circle cx="50" cy="50" r="40" fill="none"
                className={gaugeColor} strokeWidth="10"
                strokeLinecap="round"
                strokeDasharray={circumference}
                strokeDashoffset={offset} />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-xl font-bold tabular-nums">{riskScore}</span>
              <span className="text-[10px] text-muted-foreground">/100</span>
            </div>
          </div>

          {/* Info */}
          <div className="flex-1 text-center sm:text-left">
            <div className="flex items-center justify-center gap-2 sm:justify-start">
              <Icon className={`h-6 w-6 ${config.color}`} />
              <span className={`text-lg font-semibold ${config.color}`}>
                {config.label}
              </span>
            </div>
            <p className="mt-1 text-sm text-muted-foreground">
              共检查 {itemsChecked} 项
            </p>
            <div className="mt-3 flex gap-3 text-xs">
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                通过 {itemsPassed}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-yellow-500" />
                警告 {itemsWarning}
              </span>
              <span className="flex items-center gap-1">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                失败 {itemsFailed}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

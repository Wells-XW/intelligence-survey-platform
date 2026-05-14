import { ShieldCheck, ShieldAlert, ShieldX, ArrowRight, Library } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import type { ScaleResponse } from '@/lib/api';

interface Props {
  scale: ScaleResponse;
  onSelect: (s: ScaleResponse) => void;
  onImport?: (s: ScaleResponse) => void;
}

const DISCIPLINE_LABELS: Record<string, string> = {
  psychology: '心理学',
  sociology: '社会学',
  education: '教育学',
  management: '管理学',
  health: '健康',
  marketing: '市场营销',
  other: '其他',
};

function AlphaIndicator({ alpha }: { alpha?: number }) {
  if (alpha === undefined || alpha === null) return null;
  const color = alpha >= 0.8 ? 'text-green-600' : alpha >= 0.7 ? 'text-yellow-600' : 'text-red-600';
  const Icon = alpha >= 0.8 ? ShieldCheck : alpha >= 0.7 ? ShieldAlert : ShieldX;
  return (
    <span className={`inline-flex items-center gap-1 text-sm font-medium ${color}`}>
      <Icon className="h-4 w-4" />
      α = {alpha.toFixed(2)}
    </span>
  );
}

export function ScaleCard({ scale, onSelect, onImport }: Props) {
  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => onSelect(scale)}>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base font-medium">{scale.name}</CardTitle>
          <span className="text-xs px-2 py-0.5 bg-secondary rounded-full whitespace-nowrap">
            {DISCIPLINE_LABELS[scale.discipline] || scale.discipline}
          </span>
        </div>
      </CardHeader>
      <CardContent className="text-sm space-y-2">
        <div className="flex items-center gap-3 flex-wrap">
          <AlphaIndicator alpha={scale.cronbach_alpha} />
          <span className="text-muted-foreground text-xs">{scale.items?.length || 0} 题</span>
          <span className="text-muted-foreground text-xs">{scale.language === 'zh' ? '中文' : 'EN'}</span>
        </div>
        {scale.description && (
          <p className="text-muted-foreground line-clamp-2">{scale.description}</p>
        )}
        <div className="flex gap-2 pt-1">
          <Button variant="outline" size="sm" className="text-xs" onClick={(e) => { e.stopPropagation(); onSelect(scale); }}>
            <Library className="h-3 w-3 mr-1" />详情
          </Button>
          {onImport && (
            <Button variant="secondary" size="sm" className="text-xs" onClick={(e) => { e.stopPropagation(); onImport(scale); }}>
              <ArrowRight className="h-3 w-3 mr-1" />导入问卷
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

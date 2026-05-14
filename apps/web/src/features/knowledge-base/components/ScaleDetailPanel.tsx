import { X, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import type { ScaleResponse } from '@/lib/api';

interface Props {
  scale: ScaleResponse | null;
  onClose: () => void;
  onImport?: (scale: ScaleResponse) => void;
}

export function ScaleDetailPanel({ scale, onClose, onImport }: Props) {
  if (!scale) return null;

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-lg bg-background border-l shadow-xl z-50 overflow-y-auto">
      <div className="sticky top-0 bg-background border-b p-4 flex items-center justify-between">
        <h3 className="font-semibold text-lg">量表详情</h3>
        <Button variant="ghost" size="icon" onClick={onClose}>
          <X className="h-5 w-5" />
        </Button>
      </div>
      <div className="p-6 space-y-5">
        <h4 className="text-xl font-semibold">{scale.name}</h4>
        {scale.description && <p className="text-muted-foreground">{scale.description}</p>}

        <div className="flex gap-4 text-sm">
          {scale.cronbach_alpha != null && (
            <div className="bg-muted px-3 py-2 rounded">
              <span className="text-muted-foreground">Cronbach's α</span>
              <p className="text-lg font-bold">{scale.cronbach_alpha.toFixed(2)}</p>
            </div>
          )}
          <div className="bg-muted px-3 py-2 rounded">
            <span className="text-muted-foreground">题数</span>
            <p className="text-lg font-bold">{scale.items?.length || 0}</p>
          </div>
          <div className="bg-muted px-3 py-2 rounded">
            <span className="text-muted-foreground">语言</span>
            <p className="text-lg font-bold">{scale.language === 'zh' ? '中文' : 'EN'}</p>
          </div>
        </div>

        {scale.cronbach_alpha_history && scale.cronbach_alpha_history.length > 0 && (
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">信度历史</p>
            <div className="space-y-1">
              {scale.cronbach_alpha_history.map((h, i) => (
                <div key={i} className="flex items-center justify-between text-sm bg-muted px-3 py-1.5 rounded">
                  <span>{h.citation?.substring(0, 60)}...</span>
                  <span className="font-mono font-bold ml-2">α={h.value.toFixed(2)} <span className="text-muted-foreground font-normal">(n={h.sample_n}, {h.year})</span></span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div>
          <p className="text-sm font-medium text-muted-foreground mb-2">题项列表</p>
          <div className="space-y-1">
            {scale.items?.map((item, i) => (
              <div key={i} className="flex items-start gap-2 text-sm bg-muted px-3 py-2 rounded">
                <span className="font-mono text-muted-foreground shrink-0">{item.code}</span>
                <span>{item.text}</span>
                {item.reverse_scored && (
                  <span className="text-xs px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded shrink-0">反向</span>
                )}
              </div>
            )) || <p className="text-muted-foreground text-sm">暂无题项</p>}
          </div>
        </div>

        {scale.citations && scale.citations.length > 0 && (
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-2">引用文献</p>
            <div className="space-y-1">
              {scale.citations.map((c, i) => (
                <p key={i} className="text-xs text-muted-foreground bg-muted px-3 py-1.5 rounded">
                  {c.authors} ({c.year}). {c.title}. {c.doi ? `DOI: ${c.doi}` : ''}
                </p>
              ))}
            </div>
          </div>
        )}

        {onImport && (
          <Button className="w-full" onClick={() => onImport(scale)}>
            <ArrowRight className="h-4 w-4 mr-2" />导入到问卷
          </Button>
        )}
      </div>
    </div>
  );
}

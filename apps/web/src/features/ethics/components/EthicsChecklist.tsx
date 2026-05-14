import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { CheckCircle, AlertTriangle, XCircle } from 'lucide-react';
import type { ComplianceFinding } from '@/lib/api';

interface EthicsChecklistProps {
  findings: ComplianceFinding[];
}

const dimLabels: Record<string, string> = {
  pipl: 'PIPL 合规',
  gdpr: 'GDPR 合规',
  bias: '方法论偏差',
  sensitive_info: '敏感信息',
  consent: '知情同意',
  minimization: '数据最小化',
  ai_informed_consent: 'AI: 知情同意',
  ai_data_minimization: 'AI: 数据最小化',
  ai_sensitive_data: 'AI: 敏感数据',
  ai_vulnerable: 'AI: 脆弱群体',
  ai_risk_benefit: 'AI: 风险收益',
  ai_cultural: 'AI: 文化适配',
  ai_wording: 'AI: 措辞伦理',
};

const severityIcon = {
  info: CheckCircle,
  warning: AlertTriangle,
  error: XCircle,
} as const;

const severityColor = {
  info: 'text-green-600',
  warning: 'text-yellow-600',
  error: 'text-red-600',
} as const;

export function EthicsChecklist({ findings }: EthicsChecklistProps) {
  // Group by dimension
  const grouped: Record<string, ComplianceFinding[]> = {};
  for (const f of findings) {
    if (!grouped[f.dimension]) grouped[f.dimension] = [];
    grouped[f.dimension].push(f);
  }

  const dimStats = Object.entries(grouped).map(([dim, items]) => {
    const errors = items.filter((i) => i.severity === 'error').length;
    const warnings = items.filter((i) => i.severity === 'warning').length;
    const passed = items.filter((i) => i.severity === 'info').length;
    return { dim, items, errors, warnings, passed };
  });

  return (
    <div className="space-y-4">
      {dimStats.map(({ dim, items, errors, warnings, passed }) => (
        <Card key={dim}>
          <CardContent className="p-4">
            <div className="mb-3 flex items-center justify-between">
              <h4 className="font-medium text-gray-900">
                {dimLabels[dim] || dim}
              </h4>
              <div className="flex gap-2">
                {errors > 0 && (
                  <Badge variant="destructive">{errors} 失败</Badge>
                )}
                {warnings > 0 && (
                  <Badge variant="secondary" className="bg-yellow-100 text-yellow-800">
                    {warnings} 警告
                  </Badge>
                )}
                {passed > 0 && (
                  <Badge variant="secondary" className="bg-green-100 text-green-800">
                    {passed} 通过
                  </Badge>
                )}
              </div>
            </div>
            <ul className="space-y-1.5">
              {items.map((item, i) => {
                const Icon = severityIcon[item.severity as keyof typeof severityIcon] || CheckCircle;
                return (
                  <li key={i} className="flex items-start gap-2 text-sm">
                    <Icon className={`mt-0.5 h-4 w-4 flex-shrink-0 ${severityColor[item.severity as keyof typeof severityColor]}`} />
                    <span className="text-gray-700">{item.issue}</span>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

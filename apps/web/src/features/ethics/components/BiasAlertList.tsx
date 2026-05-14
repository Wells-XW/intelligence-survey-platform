import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { AlertTriangle, BookOpen } from 'lucide-react';
import type { ComplianceSuggestion } from '@/lib/api';

interface BiasAlertListProps {
  suggestions: ComplianceSuggestion[];
}

const priorityBadge: Record<string, { variant: 'destructive' | 'secondary' | 'outline'; label: string }> = {
  critical: { variant: 'destructive', label: '紧急' },
  high: { variant: 'destructive', label: '高优先级' },
  medium: { variant: 'secondary', label: '中优先级' },
  low: { variant: 'outline', label: '低优先级' },
};

export function BiasAlertList({ suggestions }: BiasAlertListProps) {
  if (suggestions.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <AlertTriangle className="mx-auto h-8 w-8 text-green-500" />
          <p className="mt-2 text-sm text-muted-foreground">
            未检测到需要改进的问题
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {suggestions.map((s, i) => {
        const badge = priorityBadge[s.priority] || priorityBadge.medium;
        return (
          <Card key={i}>
            <CardContent className="p-4">
              <div className="mb-2 flex items-center justify-between">
                <h4 className="font-medium text-gray-900">{s.title}</h4>
                <Badge variant={badge.variant}>{badge.label}</Badge>
              </div>
              <p className="text-sm text-muted-foreground">{s.description}</p>
              {s.reference && (
                <div className="mt-2 flex items-center gap-1 text-xs text-muted-foreground">
                  <BookOpen className="h-3 w-3" />
                  <span>{s.reference}</span>
                </div>
              )}
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

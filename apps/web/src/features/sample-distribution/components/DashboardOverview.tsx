import { useQuery } from '@tanstack/react-query';
import { Users, CheckCircle, SendHorizonal, Target } from 'lucide-react';
import { getDistributionDashboard, type DistributionDashboard } from '@/lib/api';
import { Card, CardContent } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';

interface Props {
  surveyId: string;
}

export function DashboardOverview({ surveyId }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['distribution-dashboard', surveyId],
    queryFn: () => getDistributionDashboard(surveyId),
  });

  if (isLoading) {
    return (
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
    );
  }

  if (error || !data) {
    return (
      <Card className="border-red-200 bg-red-50">
        <CardContent className="py-6 text-center text-red-600">
          加载失败，请重试
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-blue-100 p-2">
                <Users className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{data.total_recipients}</p>
                <p className="text-xs text-muted-foreground">受访者总数</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-green-100 p-2">
                <CheckCircle className="h-5 w-5 text-green-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{data.total_responded}</p>
                <p className="text-xs text-muted-foreground">
                  已完成 · {data.response_rate}%
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-purple-100 p-2">
                <SendHorizonal className="h-5 w-5 text-purple-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{data.total_distributions}</p>
                <p className="text-xs text-muted-foreground">
                  发放次数 · {data.active_distributions} 活跃
                </p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-amber-100 p-2">
                <Target className="h-5 w-5 text-amber-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{data.quotas.length}</p>
                <p className="text-xs text-muted-foreground">配额定义</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Quota Progress */}
      {data.quotas.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <h3 className="font-semibold text-sm mb-4">配额填充进度</h3>
            <div className="space-y-3">
              {data.quotas.map((q) => {
                const fillColor =
                  q.fill_rate >= 80
                    ? 'bg-green-500'
                    : q.fill_rate >= 50
                      ? 'bg-amber-500'
                      : 'bg-red-500';
                return (
                  <div key={q.id}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="font-medium">
                        {q.name}
                        {!q.is_active && (
                          <span className="ml-1 text-xs text-muted-foreground">
                            (已暂停)
                          </span>
                        )}
                      </span>
                      <span className="text-muted-foreground">
                        {q.current_count}/{q.target_count} · {q.fill_rate}%
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-muted overflow-hidden">
                      <div
                        className={cn('h-full rounded-full transition-all', fillColor)}
                        style={{ width: `${Math.min(q.fill_rate, 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Sample Groups Summary */}
      {data.sample_groups.length > 0 && (
        <Card>
          <CardContent className="pt-6">
            <h3 className="font-semibold text-sm mb-3">样本组 ({data.sample_groups.length})</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {data.sample_groups.map((g) => (
                <div
                  key={g.id}
                  className="flex items-center justify-between rounded-lg border p-3"
                >
                  <div>
                    <p className="font-medium text-sm">{g.name}</p>
                    {g.description && (
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {g.description}
                      </p>
                    )}
                  </div>
                  <span className="text-sm font-semibold text-muted-foreground">
                    {g.recipient_count} 人
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

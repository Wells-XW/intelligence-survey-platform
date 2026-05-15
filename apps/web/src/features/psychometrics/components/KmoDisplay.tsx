import { Activity } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { KmoBartlettResult } from '@/lib/api';

interface Props {
  data: KmoBartlettResult | null;
  isLoading?: boolean;
}

const KMO_COLORS: Record<number, { color: string; label: string }> = {
  0.9: { color: '#16a34a', label: '极佳' },
  0.8: { color: '#65a30d', label: '良好' },
  0.7: { color: '#ca8a04', label: '一般' },
  0.6: { color: '#d97706', label: '勉强' },
  0.5: { color: '#dc2626', label: '不足' },
  0.0: { color: '#991b1b', label: '不适合' },
};

function getKmoColor(km: number): { color: string; label: string } {
  for (const [threshold, info] of Object.entries(KMO_COLORS).sort(
    (a, b) => Number(b[0]) - Number(a[0]),
  )) {
    if (km >= Number(threshold)) return info;
  }
  return KMO_COLORS[0.0];
}

export function KmoDisplay({ data, isLoading }: Props) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader><CardTitle>因子分析适宜性</CardTitle></CardHeader>
        <CardContent><p className="text-muted-foreground">计算中…</p></CardContent>
      </Card>
    );
  }

  if (!data || data.error) {
    return (
      <Card>
        <CardHeader><CardTitle>因子分析适宜性</CardTitle></CardHeader>
        <CardContent>
          <p className="text-muted-foreground">{data?.error || '暂无数据'}</p>
        </CardContent>
      </Card>
    );
  }

  const kmoInfo = getKmoColor(data.kmo_overall ?? 0);
  const kmoDeg = Math.min((data.kmo_overall ?? 0) * 180, 180);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Activity className="h-5 w-5" />
          因子分析适宜性
        </CardTitle>
        <p className="text-xs text-muted-foreground">N = {data.n_valid}</p>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* KMO Gauge */}
        <div className="flex flex-col items-center">
          <div className="relative w-40 h-20 overflow-hidden">
            <div
              className="absolute bottom-0 left-0 w-full h-40 rounded-t-full"
              style={{
                background: `conic-gradient(from 180deg, ${kmoInfo.color} ${kmoDeg}deg, #e5e7eb ${kmoDeg}deg)`,
                clipPath: 'inset(0 0 50% 0)',
              }}
            />
            <div className="absolute bottom-0 left-1/2 -translate-x-1/2 text-center">
              <p className="text-3xl font-bold" style={{ color: kmoInfo.color }}>
                {data.kmo_overall !== null ? data.kmo_overall.toFixed(3) : 'N/A'}
              </p>
            </div>
          </div>
          <p className="text-sm mt-1 font-medium" style={{ color: kmoInfo.color }}>
            {kmoInfo.label} — {data.interpretation || ''}
          </p>
        </div>

        {/* Bartlett's Test */}
        {data.bartlett_chi_square !== null && (
          <div className="grid grid-cols-3 gap-3 text-center">
            <div className="bg-muted rounded p-2">
              <p className="text-xs text-muted-foreground">χ²</p>
              <p className="font-mono font-bold">
                {data.bartlett_chi_square.toFixed(2)}
              </p>
            </div>
            <div className="bg-muted rounded p-2">
              <p className="text-xs text-muted-foreground">df</p>
              <p className="font-mono font-bold">{data.bartlett_df}</p>
            </div>
            <div className="bg-muted rounded p-2">
              <p className="text-xs text-muted-foreground">p 值</p>
              <p className={`font-mono font-bold ${
                (data.bartlett_p_value ?? 1) < 0.05 ? 'text-green-600' : 'text-red-600'
              }`}>
                {data.bartlett_p_value !== null ? data.bartlett_p_value.toFixed(4) : 'N/A'}
              </p>
            </div>
          </div>
        )}

        {data.bartlett_p_value !== null && (
          <div className="bg-muted rounded p-2 text-sm">
            <span className="font-medium">Bartlett 检验：</span>
            {(data.bartlett_p_value ?? 1) < 0.001
              ? 'p < 0.001，相关矩阵与单位矩阵有极显著差异，数据适合因子分析。'
              : (data.bartlett_p_value ?? 1) < 0.05
                ? `p = ${data.bartlett_p_value!.toFixed(3)} < 0.05，相关矩阵与单位矩阵有显著差异，数据适合因子分析。`
                : `p = ${data.bartlett_p_value!.toFixed(3)} ≥ 0.05，相关矩阵与单位矩阵无显著差异，数据可能不适合因子分析。`}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

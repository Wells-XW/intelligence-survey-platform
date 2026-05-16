import { useState, useEffect, useCallback } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import {
  Ruler,
  ClipboardList,
  Gauge,
  BarChart3,
  Activity,
} from 'lucide-react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  getSplitHalf,
  getItemTotal,
  getKmoBartlett,
  analyzeConstructs,
  getPsychometricReport,
  compareReliabilityNorms,
  type ConstructPsychometricsResult,
  type PsychometricReportResponse,
  type ReliabilityNormComparisonResult,
} from '@/lib/api';
import { usePsychometricsStore } from '@/features/psychometrics/store';
import {
  ConstructBuilder,
  SplitHalfDisplay,
  ItemTotalTable,
  KmoDisplay,
  PsychometricReport,
  ReliabilityComparison,
} from '@/features/psychometrics/components';

export function MeasurementToolkitPage() {
  const { id: surveyId } = useParams<{ id: string }>();
  const store = usePsychometricsStore();

  // State for manual item input
  const [itemsInput, setItemsInput] = useState('');

  // Fetch available items via analytics summary
  const { data: summaryData } = useQuery({
    queryKey: ['analytics-summary', surveyId],
    queryFn: async () => {
      // Reuse existing analytics summary endpoint to get item names
      const { api } = await import('@/lib/api');
      interface SurveySummary {
        questions: Array<{
          question_name: string;
          question_text: string;
          question_type: string;
        }>;
      }
      const data = await api.get<SurveySummary>(
        `/surveys/${surveyId}/analytics/summary`,
      );
      return data;
    },
    enabled: !!surveyId,
  });

  // Populate available Likert items
  useEffect(() => {
    if (summaryData?.questions) {
      const likertItems = summaryData.questions
        .filter((q) => q.question_type === 'rating')
        .map((q) => ({
          name: q.question_name,
          title: q.question_text || q.question_name,
          type: 'rating',
        }));
      store.setAvailableItems(likertItems);
    }
  }, [summaryData, store]);

  // Derive selected items from store or input
  const itemsStr = store.selectedItems.length > 0
    ? store.selectedItems.join(',')
    : itemsInput;

  const commonQueryKey = ['psychometrics', surveyId, itemsStr];

  // Split-half query
  const splitHalfQuery = useQuery({
    queryKey: [...commonQueryKey, 'split-half', store.splitMethod],
    queryFn: () => getSplitHalf(surveyId!, itemsStr || undefined, store.splitMethod),
    enabled: !!surveyId && !!itemsStr,
  });

  // Item-total query
  const itemTotalQuery = useQuery({
    queryKey: [...commonQueryKey, 'item-total'],
    queryFn: () => getItemTotal(surveyId!, itemsStr || undefined),
    enabled: !!surveyId && !!itemsStr,
  });

  // KMO query
  const kmoQuery = useQuery({
    queryKey: [...commonQueryKey, 'kmo'],
    queryFn: () => getKmoBartlett(surveyId!, itemsStr || undefined),
    enabled: !!surveyId && !!itemsStr,
  });

  // Constructs analysis (manual trigger)
  const [constructsResult, setConstructsResult] = useState<ConstructPsychometricsResult | null>(null);
  const [constructsLoading, setConstructsLoading] = useState(false);
  const handleAnalyzeConstructs = useCallback(async (constructs: Array<{ name: string; items: string[] }>) => {
    if (!surveyId) return;
    setConstructsLoading(true);
    try {
      const res = await analyzeConstructs(surveyId!, constructs);
      setConstructsResult(res);
      store.setConstructsResult(res);
    } catch {
      // error handled by query
    } finally {
      setConstructsLoading(false);
    }
  }, [surveyId, store]);

  // Report query (manual trigger)
  const [reportResult, setReportResult] = useState<PsychometricReportResponse | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const handleGenerateReport = useCallback(async () => {
    if (!surveyId) return;
    setReportLoading(true);
    try {
      const res = await getPsychometricReport(
        surveyId!,
        itemsStr || undefined,
        store.constructs.length > 0 ? JSON.stringify(store.constructs) : undefined,
      );
      setReportResult(res);
      store.setReportResult(res);
    } catch {
      // error handled
    } finally {
      setReportLoading(false);
    }
  }, [surveyId, itemsStr, store]);

  const [normResult, setNormResult] = useState<ReliabilityNormComparisonResult | null>(null);
  const [normLoading, setNormLoading] = useState(false);
  const handleCompareNorms = useCallback(async () => {
    if (!surveyId) return;
    setNormLoading(true);
    try {
      const res = await compareReliabilityNorms(surveyId!, itemsStr || undefined);
      setNormResult(res);
      store.setNormResult(res);
    } catch {
      // error handled
    } finally {
      setNormLoading(false);
    }
  }, [surveyId, itemsStr, store]);

  useEffect(() => {
    if (splitHalfQuery.data) store.setSplitHalfResult(splitHalfQuery.data);
    if (itemTotalQuery.data) store.setItemTotalResult(itemTotalQuery.data);
    if (kmoQuery.data) store.setKmoResult(kmoQuery.data);
  }, [splitHalfQuery.data, itemTotalQuery.data, kmoQuery.data, store]);

  if (!surveyId) return null;

  return (
    <div className="mx-auto max-w-6xl p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">测量工具箱</h1>
          <p className="text-sm text-muted-foreground">
            心理计量学分析：信度、效度、因子分析适宜性
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline">
            {store.availableItems.length} Likert 题项
          </Badge>
        </div>
      </div>

      {/* Item selector */}
      <div className="flex items-center gap-3 bg-muted/50 rounded-lg p-3">
        <label className="text-sm font-medium whitespace-nowrap">分析题项:</label>
        <input
          type="text"
          className="flex-1 rounded border border-border bg-background px-3 py-1.5 text-sm font-mono"
          placeholder="Q1,Q2,Q3 (逗号分隔，留空则自动检测 Likert 题项)"
          value={itemsInput}
          onChange={(e) => setItemsInput(e.target.value)}
        />
        {store.availableItems.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {store.availableItems.map((item) => (
              <Badge
                key={item.name}
                variant={store.selectedItems.includes(item.name) ? 'default' : 'outline'}
                className="cursor-pointer text-xs"
                onClick={() => store.toggleItem(item.name)}
              >
                {item.name}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Tabs */}
      <Tabs defaultValue="constructs" className="w-full">
        <TabsList className="w-full">
          <TabsTrigger value="constructs" className="flex-1">
            <ClipboardList className="h-4 w-4 mr-1" />
            构念构建
          </TabsTrigger>
          <TabsTrigger value="report" className="flex-1">
            <BarChart3 className="h-4 w-4 mr-1" />
            计量报告
          </TabsTrigger>
          <TabsTrigger value="norms" className="flex-1">
            <Gauge className="h-4 w-4 mr-1" />
            常模比较
          </TabsTrigger>
          <TabsTrigger value="details" className="flex-1">
            <Ruler className="h-4 w-4 mr-1" />
            详细指标
          </TabsTrigger>
        </TabsList>

        {/* Construct Builder Tab */}
        <TabsContent value="constructs" className="mt-4">
          <ConstructBuilder
            onAnalyze={handleAnalyzeConstructs}
            isAnalyzing={constructsLoading}
          />
          {constructsResult && (
            <div className="mt-6 space-y-4">
              <h2 className="font-semibold text-lg">分析结果</h2>
              {constructsResult.constructs.map((c) => (
                <div key={c.name} className="border border-border rounded-lg p-4">
                  <h3 className="font-medium flex items-center gap-2">
                    {c.name}
                    <Badge variant="secondary">{c.n_items} 题项</Badge>
                    <Badge variant="outline">N={c.n_valid}</Badge>
                  </h3>
                  <div className="grid grid-cols-2 gap-3 mt-2">
                    <div className="bg-muted rounded p-2 text-center">
                      <p className="text-xs text-muted-foreground">Cronbach's α</p>
                      <p className="text-xl font-bold font-mono">
                        {c.cronbach_alpha?.toFixed(3) ?? 'N/A'}
                      </p>
                      <p className="text-xs text-muted-foreground">{c.alpha_interpretation}</p>
                    </div>
                    <div className="bg-muted rounded p-2 text-center">
                      <p className="text-xs text-muted-foreground">分半信度 (SB)</p>
                      <p className="text-xl font-bold font-mono">
                        {c.split_half?.toFixed(3) ?? 'N/A'}
                      </p>
                    </div>
                  </div>
                </div>
              ))}

              {/* Inter-construct correlations */}
              {constructsResult.inter_correlations.length > 0 && (
                <div className="border border-border rounded-lg p-4">
                  <h3 className="font-medium mb-2">构念间相关</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {constructsResult.inter_correlations.map((ic) => (
                      <div key={`${ic.construct_a}-${ic.construct_b}`} className="bg-muted rounded p-2 text-sm">
                        <span className="font-mono">{ic.construct_a}</span>
                        {' ↔ '}
                        <span className="font-mono">{ic.construct_b}</span>
                        <span className="ml-2 font-bold text-accent">
                          r = {ic.correlation?.toFixed(3) ?? 'N/A'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </TabsContent>

        {/* Report Tab */}
        <TabsContent value="report" className="mt-4">
          <div className="space-y-3">
            <Button onClick={handleGenerateReport} disabled={reportLoading}>
              <Activity className="h-4 w-4 mr-1" />
              {reportLoading ? '生成中…' : '生成报告'}
            </Button>
            <PsychometricReport data={reportResult} isLoading={reportLoading} />
          </div>
        </TabsContent>

        {/* Norm Comparison Tab */}
        <TabsContent value="norms" className="mt-4">
          <div className="space-y-3">
            <Button onClick={handleCompareNorms} disabled={normLoading}>
              <Gauge className="h-4 w-4 mr-1" />
              {normLoading ? '比较中…' : '比较常模'}
            </Button>
            <ReliabilityComparison data={normResult} isLoading={normLoading} />
          </div>
        </TabsContent>

        {/* Detail Metrics Tab */}
        <TabsContent value="details" className="mt-4">
          <div className="grid gap-4 md:grid-cols-2">
            <SplitHalfDisplay data={splitHalfQuery.data ?? null} isLoading={splitHalfQuery.isLoading} />
            <KmoDisplay data={kmoQuery.data ?? null} isLoading={kmoQuery.isLoading} />
            <div className="md:col-span-2">
              <ItemTotalTable data={itemTotalQuery.data ?? null} isLoading={itemTotalQuery.isLoading} />
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

import { useParams } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import { Shield, RefreshCw, FileText, History } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useEthicsStore } from '@/features/ethics/store';
import {
  EthicsChecklist,
  RiskRadar,
  ComplianceReport,
  BiasAlertList,
} from '@/features/ethics/components';
import {
  runComplianceScan,
  getComplianceReport,
  getComplianceHistory,
} from '@/lib/api';

export function EthicsCompliancePage() {
  const { id } = useParams<{ id: string }>();
  const surveyId = id!;
  const store = useEthicsStore();

  // Scan mutation
  const scanMutation = useMutation({
    mutationFn: () =>
      runComplianceScan(surveyId, {
        include_ai_review: store.includeAiReview,
        check_types: store.selectedChecks.length > 0 ? store.selectedChecks : undefined,
      }),
    onSuccess: (data) => {
      store.setCurrentCheck(data);
      store.setIsScanning(false);
    },
    onError: () => {
      store.setIsScanning(false);
    },
  });

  // Report query
  const reportQuery = useQuery({
    queryKey: ['compliance-report', surveyId],
    queryFn: () => getComplianceReport(surveyId),
    enabled: false,
  });

  // History query
  const historyQuery = useQuery({
    queryKey: ['compliance-history', surveyId],
    queryFn: () => getComplianceHistory(surveyId),
    enabled: false,
  });

  const handleScan = () => {
    store.setIsScanning(true);
    scanMutation.mutate();
  };

  const handleReport = () => {
    store.setIsReportLoading(true);
    reportQuery.refetch().then((result) => {
      if (result.data) store.setReport(result.data);
      store.setIsReportLoading(false);
    });
  };

  const check = store.currentCheck;

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">伦理合规审查</h1>
          <p className="text-sm text-muted-foreground">
            PIPL / GDPR / 方法论偏差 / 敏感信息 / 知情同意
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => historyQuery.refetch()}
          >
            <History className="mr-1 h-4 w-4" />
            历史记录
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={handleReport}
            disabled={store.isReportLoading}
          >
            <FileText className="mr-1 h-4 w-4" />
            生成报告
          </Button>
          <Button
            onClick={handleScan}
            disabled={store.isScanning}
          >
            <RefreshCw
              className={`mr-1 h-4 w-4 ${store.isScanning ? 'animate-spin' : ''}`}
            />
            {store.isScanning ? '扫描中...' : '运行扫描'}
          </Button>
        </div>
      </div>

      {/* Scanning state */}
      {store.isScanning && (
        <Card>
          <CardContent className="py-8 text-center">
            <Shield className="mx-auto h-12 w-12 animate-pulse text-blue-500" />
            <p className="mt-4 text-sm text-muted-foreground">
              正在扫描问卷内容，检查合规性问题...
            </p>
          </CardContent>
        </Card>
      )}

      {/* Error state */}
      {scanMutation.isError && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="py-4 text-center text-sm text-red-700">
            扫描失败，请重试。
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {check && !store.isScanning && (
        <div className="space-y-6">
          {/* Risk Radar */}
          <RiskRadar
            riskScore={check.risk_score}
            riskLevel={check.risk_level}
            itemsChecked={check.items_checked}
            itemsPassed={check.items_passed}
            itemsWarning={check.items_warning}
            itemsFailed={check.items_failed}
          />

          {/* Tabs: Findings vs Suggestions */}
          <Tabs defaultValue="findings">
            <TabsList>
              <TabsTrigger value="findings">
                检查发现 ({check.findings.length})
              </TabsTrigger>
              <TabsTrigger value="suggestions">
                改进建议 ({check.suggestions.length})
              </TabsTrigger>
            </TabsList>
            <TabsContent value="findings" className="mt-4">
              <EthicsChecklist findings={check.findings} />
            </TabsContent>
            <TabsContent value="suggestions" className="mt-4">
              <BiasAlertList suggestions={check.suggestions} />
            </TabsContent>
          </Tabs>
        </div>
      )}

      {/* Report */}
      {store.report && (
        <div className="mt-6">
          <ComplianceReport
            reportMarkdown={store.report.report_markdown}
            surveyTitle={store.report.survey_title}
            generatedAt={store.report.generated_at}
          />
        </div>
      )}

      {/* History */}
      {historyQuery.data && (
        <Card className="mt-6">
          <CardContent className="p-5">
            <h3 className="mb-4 font-medium text-gray-900">
              历史扫描记录 ({historyQuery.data.total_checks})
            </h3>
            <div className="space-y-2">
              {historyQuery.data.checks.map((c) => (
                <div
                  key={c.id}
                  className="flex items-center justify-between rounded-lg border p-3 text-sm"
                >
                  <div>
                    <span className="font-medium">{c.check_type}</span>
                    <span className="ml-2 text-muted-foreground">
                      {new Date(c.checked_at).toLocaleString('zh-CN')}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    <span
                      className={`rounded px-2 py-0.5 text-xs font-medium ${
                        c.risk_level === 'critical'
                          ? 'bg-red-100 text-red-800'
                          : c.risk_level === 'high'
                            ? 'bg-orange-100 text-orange-800'
                            : c.risk_level === 'medium'
                              ? 'bg-yellow-100 text-yellow-800'
                              : 'bg-green-100 text-green-800'
                      }`}
                    >
                      {c.risk_level.toUpperCase()}
                    </span>
                    <span className="text-muted-foreground">
                      {c.risk_score}/100
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!check && !store.isScanning && (
        <Card>
          <CardContent className="py-12 text-center">
            <Shield className="mx-auto h-16 w-16 text-muted-foreground/40" />
            <p className="mt-4 text-muted-foreground">
              点击「运行扫描」开始检查问卷的伦理合规性
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              包含 PIPL / GDPR / 偏差检测 / 敏感信息 / 知情同意等检查
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

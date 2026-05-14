import { useParams } from 'react-router-dom';
import { Users, BarChart3, Send, Target } from 'lucide-react';
import {
  DISTRIBUTION_TABS,
  useSampleDistributionStore,
} from '@/features/sample-distribution/store';
import {
  DashboardOverview,
  SampleGroupList,
  DistributionList,
  QuotaList,
} from '@/features/sample-distribution/components';
import { Card, CardContent } from '@/components/ui/card';

export function SampleDistributionPage() {
  const { id: surveyId } = useParams<{ id: string }>();
  const { activeTab, setActiveTab } = useSampleDistributionStore();

  if (!surveyId) {
    return (
      <Card className="border-red-200 bg-red-50">
        <CardContent className="py-6 text-center text-red-600">
          问卷 ID 无效
        </CardContent>
      </Card>
    );
  }

  const tabIcons: Record<string, React.ReactNode> = {
    dashboard: <BarChart3 className="h-4 w-4" />,
    'sample-groups': <Users className="h-4 w-4" />,
    distribution: <Send className="h-4 w-4" />,
    quotas: <Target className="h-4 w-4" />,
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 px-4 py-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold">样本与发放管理</h1>
        <p className="text-sm text-muted-foreground mt-1">
          管理受访者样本、创建发放和配额控制
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-1 border-b border-border overflow-x-auto">
        {DISTRIBUTION_TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={
              `flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
                activeTab === tab.key
                  ? 'border-accent text-accent'
                  : 'border-transparent text-muted-foreground hover:text-foreground'
              }`
            }
          >
            {tabIcons[tab.key]}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="min-h-[400px]">
        {activeTab === 'dashboard' && <DashboardOverview surveyId={surveyId} />}
        {activeTab === 'sample-groups' && <SampleGroupList surveyId={surveyId} />}
        {activeTab === 'distribution' && <DistributionList surveyId={surveyId} />}
        {activeTab === 'quotas' && <QuotaList surveyId={surveyId} />}
      </div>
    </div>
  );
}

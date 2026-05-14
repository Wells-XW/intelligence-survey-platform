import { create } from 'zustand';

interface AnalyticsTab {
  key: 'summary' | 'crosstab' | 'reliability' | 'quality';
  label: string;
}

export const ANALYTICS_TABS: AnalyticsTab[] = [
  { key: 'summary', label: '描述统计' },
  { key: 'crosstab', label: '交叉分析' },
  { key: 'reliability', label: '信度分析' },
  { key: 'quality', label: '数据质量' },
];

interface AnalyticsStore {
  activeTab: AnalyticsTab['key'];
  setActiveTab: (tab: AnalyticsTab['key']) => void;
  // Cross-tab selections
  rowQuestion: string | null;
  colQuestion: string | null;
  setCrossTabQuestions: (row: string, col: string) => void;
  // Reliability scale
  scaleItems: string | null;
  scaleName: string;
  setScaleItems: (items: string | null, name?: string) => void;
}

export const useAnalyticsStore = create<AnalyticsStore>((set) => ({
  activeTab: 'summary',
  setActiveTab: (tab) => set({ activeTab: tab }),
  rowQuestion: null,
  colQuestion: null,
  setCrossTabQuestions: (row, col) =>
    set({ rowQuestion: row, colQuestion: col }),
  scaleItems: null,
  scaleName: '默认量表',
  setScaleItems: (items, name) =>
    set({ scaleItems: items, scaleName: name ?? '默认量表' }),
}));

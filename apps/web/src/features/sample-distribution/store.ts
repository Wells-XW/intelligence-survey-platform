import { create } from 'zustand';

type TabKey = 'dashboard' | 'sample-groups' | 'distribution' | 'quotas';

interface SampleDistributionState {
  activeTab: TabKey;
  setActiveTab: (tab: TabKey) => void;
  selectedGroupId: string | null;
  setSelectedGroupId: (id: string | null) => void;
  selectedDistributionId: string | null;
  setSelectedDistributionId: (id: string | null) => void;
  importDialogOpen: boolean;
  setImportDialogOpen: (open: boolean) => void;
}

export const useSampleDistributionStore = create<SampleDistributionState>(
  (set) => ({
    activeTab: 'dashboard',
    setActiveTab: (tab) => set({ activeTab: tab }),
    selectedGroupId: null,
    setSelectedGroupId: (id) => set({ selectedGroupId: id }),
    selectedDistributionId: null,
    setSelectedDistributionId: (id) => set({ selectedDistributionId: id }),
    importDialogOpen: false,
    setImportDialogOpen: (open) => set({ importDialogOpen: open }),
  }),
);

export const DISTRIBUTION_TABS: { key: TabKey; label: string }[] = [
  { key: 'dashboard', label: '概览' },
  { key: 'sample-groups', label: '样本组' },
  { key: 'distribution', label: '发放' },
  { key: 'quotas', label: '配额' },
];

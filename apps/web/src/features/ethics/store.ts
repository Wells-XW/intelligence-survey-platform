import { create } from 'zustand';
import type { ComplianceCheckResponse, ComplianceReportResponse } from '@/lib/api';

interface EthicsState {
  // Current scan result
  currentCheck: ComplianceCheckResponse | null;
  // Scan history
  history: ComplianceCheckResponse[];
  // Report
  report: ComplianceReportResponse | null;
  // UI state
  isScanning: boolean;
  isReportLoading: boolean;
  // Focus areas for scan
  selectedChecks: string[];
  includeAiReview: boolean;

  // Actions
  setCurrentCheck: (check: ComplianceCheckResponse | null) => void;
  setHistory: (history: ComplianceCheckResponse[]) => void;
  setReport: (report: ComplianceReportResponse | null) => void;
  setIsScanning: (v: boolean) => void;
  setIsReportLoading: (v: boolean) => void;
  setSelectedChecks: (checks: string[]) => void;
  setIncludeAiReview: (v: boolean) => void;
  reset: () => void;
}

export const useEthicsStore = create<EthicsState>((set) => ({
  currentCheck: null,
  history: [],
  report: null,
  isScanning: false,
  isReportLoading: false,
  selectedChecks: [],
  includeAiReview: false,

  setCurrentCheck: (check) => set({ currentCheck: check }),
  setHistory: (history) => set({ history }),
  setReport: (report) => set({ report }),
  setIsScanning: (v) => set({ isScanning: v }),
  setIsReportLoading: (v) => set({ isReportLoading: v }),
  setSelectedChecks: (checks) => set({ selectedChecks: checks }),
  setIncludeAiReview: (v) => set({ includeAiReview: v }),
  reset: () =>
    set({
      currentCheck: null,
      history: [],
      report: null,
      isScanning: false,
      isReportLoading: false,
      selectedChecks: [],
      includeAiReview: false,
    }),
}));

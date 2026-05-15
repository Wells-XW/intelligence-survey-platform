import { create } from 'zustand';
import type {
  ConstructDefinition,
  SplitHalfResult,
  ItemTotalCorrelationResult,
  KmoBartlettResult,
  ConstructPsychometricsResult,
  PsychometricReportResponse,
  ReliabilityNormComparisonResult,
} from '@/lib/api';

interface PsychometricsState {
  // Selected items for analysis
  selectedItems: string[];
  setSelectedItems: (items: string[]) => void;
  toggleItem: (itemName: string) => void;

  // Split-half method
  splitMethod: 'odd_even' | 'first_second';
  setSplitMethod: (m: 'odd_even' | 'first_second') => void;

  // Constructs
  constructs: ConstructDefinition[];
  setConstructs: (c: ConstructDefinition[]) => void;
  addConstruct: (name: string) => void;
  removeConstruct: (name: string) => void;
  addItemToConstruct: (constructName: string, itemName: string) => void;
  removeItemFromConstruct: (constructName: string, itemName: string) => void;

  // Results cache
  splitHalfResult: SplitHalfResult | null;
  setSplitHalfResult: (r: SplitHalfResult | null) => void;

  itemTotalResult: ItemTotalCorrelationResult | null;
  setItemTotalResult: (r: ItemTotalCorrelationResult | null) => void;

  kmoResult: KmoBartlettResult | null;
  setKmoResult: (r: KmoBartlettResult | null) => void;

  constructsResult: ConstructPsychometricsResult | null;
  setConstructsResult: (r: ConstructPsychometricsResult | null) => void;

  reportResult: PsychometricReportResponse | null;
  setReportResult: (r: PsychometricReportResponse | null) => void;

  normResult: ReliabilityNormComparisonResult | null;
  setNormResult: (r: ReliabilityNormComparisonResult | null) => void;

  // Available items (set externally from survey data)
  availableItems: Array<{ name: string; title: string; type: string }>;
  setAvailableItems: (items: Array<{ name: string; title: string; type: string }>) => void;
}

export const usePsychometricsStore = create<PsychometricsState>((set) => ({
  selectedItems: [],
  setSelectedItems: (items) => set({ selectedItems: items }),
  toggleItem: (name) =>
    set((s) => ({
      selectedItems: s.selectedItems.includes(name)
        ? s.selectedItems.filter((i) => i !== name)
        : [...s.selectedItems, name],
    })),

  splitMethod: 'odd_even',
  setSplitMethod: (m) => set({ splitMethod: m }),

  constructs: [],
  setConstructs: (c) => set({ constructs: c }),
  addConstruct: (name) =>
    set((s) => {
      if (s.constructs.find((c) => c.name === name)) return s;
      return { constructs: [...s.constructs, { name, items: [] }] };
    }),
  removeConstruct: (name) =>
    set((s) => ({
      constructs: s.constructs.filter((c) => c.name !== name),
    })),
  addItemToConstruct: (cName, iName) =>
    set((s) => ({
      constructs: s.constructs.map((c) => {
        if (c.name !== cName) return c;
        if (c.items.includes(iName)) return c;
        return { ...c, items: [...c.items, iName] };
      }),
    })),
  removeItemFromConstruct: (cName, iName) =>
    set((s) => ({
      constructs: s.constructs.map((c) => {
        if (c.name !== cName) return c;
        return { ...c, items: c.items.filter((i) => i !== iName) };
      }),
    })),

  splitHalfResult: null,
  setSplitHalfResult: (r) => set({ splitHalfResult: r }),
  itemTotalResult: null,
  setItemTotalResult: (r) => set({ itemTotalResult: r }),
  kmoResult: null,
  setKmoResult: (r) => set({ kmoResult: r }),
  constructsResult: null,
  setConstructsResult: (r) => set({ constructsResult: r }),
  reportResult: null,
  setReportResult: (r) => set({ reportResult: r }),
  normResult: null,
  setNormResult: (r) => set({ normResult: r }),

  availableItems: [],
  setAvailableItems: (items) => set({ availableItems: items }),
}));

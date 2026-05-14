import { create } from 'zustand';
import type {
  LiteratureResult,
  LiteratureSearchResponse,
  ScaleResponse,
  KnowledgeEntryResponse,
  AiAssistedSearchResponse,
} from '@/lib/api';

interface KnowledgeBaseState {
  // Literature search
  searchQuery: string;
  searchSource: string;
  searchResults: LiteratureResult[];
  searchTotal: number;
  isSearching: boolean;
  searchCached: boolean;
  selectedResult: LiteratureResult | null;

  // Scales
  scaleResults: ScaleResponse[];
  scaleTotal: number;
  selectedScale: ScaleResponse | null;
  scaleDiscipline: string;

  // Knowledge entries
  entryResults: KnowledgeEntryResponse[];
  entryTotal: number;
  entryCategory: string;

  // AI-assisted
  aiResult: AiAssistedSearchResponse | null;
  isAiSearching: boolean;

  // Actions
  setSearchQuery: (query: string) => void;
  setSearchSource: (source: string) => void;
  setSearchResults: (data: LiteratureSearchResponse) => void;
  setIsSearching: (v: boolean) => void;
  setSelectedResult: (r: LiteratureResult | null) => void;
  setSelectedScale: (r: ScaleResponse | null) => void;
  setScales: (results: ScaleResponse[], total: number) => void;
  setScaleDiscipline: (d: string) => void;
  setEntries: (results: KnowledgeEntryResponse[], total: number) => void;
  setEntryCategory: (c: string) => void;
  setAiResult: (r: AiAssistedSearchResponse | null) => void;
  setIsAiSearching: (v: boolean) => void;
  reset: () => void;
}

const initialState = {
  searchQuery: '',
  searchSource: 'all',
  searchResults: [] as LiteratureResult[],
  searchTotal: 0,
  isSearching: false,
  searchCached: false,
  selectedResult: null as LiteratureResult | null,

  scaleResults: [] as ScaleResponse[],
  scaleTotal: 0,
  selectedScale: null as ScaleResponse | null,
  scaleDiscipline: '',

  entryResults: [] as KnowledgeEntryResponse[],
  entryTotal: 0,
  entryCategory: '',

  aiResult: null as AiAssistedSearchResponse | null,
  isAiSearching: false,
};

export const useKnowledgeBaseStore = create<KnowledgeBaseState>((set) => ({
  ...initialState,

  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setSearchSource: (searchSource) => set({ searchSource }),
  setSearchResults: (data) =>
    set({
      searchResults: data.results,
      searchTotal: data.total_count,
      searchCached: data.cached,
    }),
  setIsSearching: (isSearching) => set({ isSearching }),
  setSelectedResult: (selectedResult) => set({ selectedResult }),
  setSelectedScale: (selectedScale) => set({ selectedScale }),
  setScales: (results, total) => set({ scaleResults: results, scaleTotal: total }),
  setScaleDiscipline: (scaleDiscipline) => set({ scaleDiscipline }),
  setEntries: (results, total) => set({ entryResults: results, entryTotal: total }),
  setEntryCategory: (entryCategory) => set({ entryCategory }),
  setAiResult: (aiResult) => set({ aiResult }),
  setIsAiSearching: (isAiSearching) => set({ isAiSearching }),
  reset: () => set(initialState),
}));

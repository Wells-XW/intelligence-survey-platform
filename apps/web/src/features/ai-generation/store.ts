import { create } from 'zustand';
import type {
  AiGenerationRequest,
  AiGenerationResponse,
  AiCostEstimate,
  SseProgressEvent,
  SqpQualitySummary,
} from '@/lib/api';

interface AiGenerationState {
  // Form state
  form: AiGenerationRequest;

  // Generation state
  isGenerating: boolean;
  progressPct: number;
  currentStage: string;
  stageMessage: string;
  events: SseProgressEvent[];

  // Results
  cost: AiCostEstimate | null;
  result: AiGenerationResponse | null;
  error: string | null;

  // Actions
  setFormField: <K extends keyof AiGenerationRequest>(
    key: K,
    value: AiGenerationRequest[K]
  ) => void;
  setCost: (cost: AiCostEstimate) => void;
  startGeneration: () => void;
  addEvent: (event: SseProgressEvent) => void;
  setResult: (result: AiGenerationResponse) => void;
  setError: (error: string) => void;
  reset: () => void;
}

const defaultForm: AiGenerationRequest = {
  topic: '',
  research_question: '',
  target_population: '',
  num_items: 20,
  language: 'zh',
};

export const useAiGenerationStore = create<AiGenerationState>((set) => ({
  form: { ...defaultForm },
  isGenerating: false,
  progressPct: 0,
  currentStage: '',
  stageMessage: '准备就绪',
  events: [],
  cost: null,
  result: null,
  error: null,

  setFormField: (key, value) =>
    set((state) => ({
      form: { ...state.form, [key]: value },
    })),

  setCost: (cost) => set({ cost }),

  startGeneration: () =>
    set({
      isGenerating: true,
      progressPct: 0,
      currentStage: 'idle',
      stageMessage: '正在启动...',
      events: [],
      result: null,
      error: null,
    }),

  addEvent: (event) =>
    set((state) => ({
      currentStage: event.stage,
      stageMessage: event.message,
      progressPct: event.progress_pct,
      events: [...state.events, event],
    })),

  setResult: (result) =>
    set({
      isGenerating: false,
      result,
      currentStage: 'done',
      stageMessage: result.success ? '生成完成！' : '生成失败',
      progressPct: 100,
    }),

  setError: (error) =>
    set({
      isGenerating: false,
      error,
      currentStage: 'error',
      stageMessage: '生成失败',
      progressPct: 100,
    }),

  reset: () =>
    set({
      form: { ...defaultForm },
      isGenerating: false,
      progressPct: 0,
      currentStage: '',
      stageMessage: '准备就绪',
      events: [],
      cost: null,
      result: null,
      error: null,
    }),
}));

import { useState } from 'react';
import { useAiGenerationStore } from '../store';
import { estimateAiCost, generateSurveyStream } from '@/lib/api';

interface Props {
  onGenerateStart: () => void;
  onGenerateComplete: () => void;
}

export function AiGenerationForm({ onGenerateStart, onGenerateComplete }: Props) {
  const {
    form, setFormField, isGenerating,
    setCost, startGeneration, addEvent, setResult, setError, cost,
  } = useAiGenerationStore();
  const [estimating, setEstimating] = useState(false);

  const handleEstimate = async () => {
    if (!form.topic || !form.research_question || !form.target_population) return;
    setEstimating(true);
    try {
      const estimate = await estimateAiCost(form);
      setCost(estimate);
    } catch {
      // estimation is optional — proceed silently
    } finally {
      setEstimating(false);
    }
  };

  const handleGenerate = async () => {
    if (!form.topic || !form.research_question || !form.target_population) return;
    startGeneration();
    onGenerateStart();

    generateSurveyStream(
      form,
      (event) => addEvent(event),
      (err) => {
        setError(err);
        onGenerateComplete();
      },
      (result) => {
        setResult(result);
        onGenerateComplete();
      }
    );
  };

  const canSubmit = form.topic.trim() && form.research_question.trim() && form.target_population.trim();

  return (
    <div className="space-y-6">
      {/* Research Topic */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          研究主题 <span className="text-destructive">*</span>
        </label>
        <input
          type="text"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="例如：网络调查的代表性偏差"
          value={form.topic}
          onChange={(e) => setFormField('topic', e.target.value)}
          disabled={isGenerating}
        />
      </div>

      {/* Research Question */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          研究问题 <span className="text-destructive">*</span>
        </label>
        <textarea
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[80px]"
          placeholder="例如：网络调查中自愿参与偏差如何影响估计精度？有哪些可行的校正策略？"
          value={form.research_question}
          onChange={(e) => setFormField('research_question', e.target.value)}
          disabled={isGenerating}
          rows={3}
        />
      </div>

      {/* Target Population */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          目标人群 <span className="text-destructive">*</span>
        </label>
        <input
          type="text"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="例如：18-60岁城镇居民"
          value={form.target_population}
          onChange={(e) => setFormField('target_population', e.target.value)}
          disabled={isGenerating}
        />
      </div>

      {/* Row: Items + Language */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1.5">目标题量</label>
          <input
            type="number"
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            min={5}
            max={100}
            value={form.num_items ?? 20}
            onChange={(e) => setFormField('num_items', parseInt(e.target.value) || 20)}
            disabled={isGenerating}
          />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1.5">问卷语言</label>
          <select
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
            value={form.language}
            onChange={(e) => setFormField('language', e.target.value as 'zh' | 'en')}
            disabled={isGenerating}
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
          </select>
        </div>
      </div>

      {/* Constructs */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          测量构念
          <span className="text-muted-foreground font-normal ml-1">（逗号分隔，可选）</span>
        </label>
        <input
          type="text"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder="例如：社会信任、政治效能感、媒介接触"
          value={(form.constructs || []).join('、')}
          onChange={(e) =>
            setFormField(
              'constructs',
              e.target.value.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
            )
          }
          disabled={isGenerating}
        />
      </div>

      {/* Methodology Notes */}
      <div>
        <label className="block text-sm font-medium mb-1.5">
          方法学要求
          <span className="text-muted-foreground font-normal ml-1">（可选）</span>
        </label>
        <textarea
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus:outline-none focus:ring-2 focus:ring-ring min-h-[60px]"
          placeholder="例如：需要使用7点Likert量表、包含2个注意力检测题、参考CGSS问卷设计..."
          value={form.methodology_notes || ''}
          onChange={(e) => setFormField('methodology_notes', e.target.value)}
          disabled={isGenerating}
          rows={2}
        />
      </div>

      {/* Cost Estimate */}
      {cost && (
        <div className="rounded-md border bg-muted/30 px-4 py-3">
          <p className="text-sm text-muted-foreground">{cost.message}</p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-3 pt-2">
        <button
          onClick={handleEstimate}
          disabled={!canSubmit || estimating || isGenerating}
          className="inline-flex items-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium shadow-sm hover:bg-accent disabled:opacity-50"
        >
          {estimating ? '估算中...' : '预估成本'}
        </button>
        <button
          onClick={handleGenerate}
          disabled={!canSubmit || isGenerating}
          className="inline-flex items-center rounded-md bg-primary px-6 py-2 text-sm font-medium text-primary-foreground shadow-sm hover:bg-primary/90 disabled:opacity-50"
        >
          {isGenerating ? '生成中...' : 'AI 生成问卷'}
        </button>
      </div>
    </div>
  );
}

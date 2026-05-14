import { useAiGenerationStore } from '../store';

const STAGE_LABELS: Record<string, string> = {
  estimating: '成本估算',
  estimated: '成本估算完成',
  prompting: '构建提示词',
  routing: '模型路由',
  generating: 'AI 生成中',
  generated: '生成完成',
  parsing: '解析结果',
  evaluating: 'SQP 质量评估',
  evaluated: '评估完成',
  done: '全部完成',
  error: '错误',
};

export function ProgressPanel() {
  const { isGenerating, progressPct, currentStage, stageMessage, events, error } =
    useAiGenerationStore();

  if (!isGenerating && events.length === 0 && !error) return null;

  return (
    <div className="rounded-lg border p-6 space-y-4">
      {/* Stage label */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">
          {STAGE_LABELS[currentStage] || currentStage || '处理中'}
        </h3>
        <span className="text-sm text-muted-foreground">{progressPct}%</span>
      </div>

      {/* Progress bar */}
      <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            error ? 'bg-destructive' : currentStage === 'done' ? 'bg-emerald-500' : 'bg-primary'
          }`}
          style={{ width: `${progressPct}%` }}
        />
      </div>

      {/* Stage message */}
      <p className={`text-sm ${error ? 'text-destructive' : 'text-muted-foreground'}`}>
        {stageMessage}
      </p>

      {/* Event timeline */}
      {events.length > 0 && (
        <div className="space-y-1.5 pt-2 border-t">
          {events.map((e, i) => (
            <div key={i} className="flex items-start gap-2 text-xs text-muted-foreground">
              <span className="mt-0.5 h-1.5 w-1.5 rounded-full bg-primary flex-shrink-0" />
              <span>{e.message}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

import type { AiCostEstimate, AiGenerationMeta } from '@/lib/api';

interface CostBadgeProps {
  cost?: AiCostEstimate | null;
  meta?: AiGenerationMeta | null;
}

export function CostBadge({ cost, meta }: CostBadgeProps) {
  const displayCost = meta?.estimated_cost_cents ?? cost?.estimated_cost_cents;
  const displayModel = meta?.model ?? cost?.model ?? 'deepseek-chat';
  const displayProvider = meta?.provider ?? cost?.provider ?? 'deepseek';

  if (!displayCost && !meta?.total_tokens) return null;

  return (
    <div className="inline-flex items-center gap-2 rounded-md border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
      <span className="font-medium">{displayProvider}/{displayModel}</span>
      <span className="text-border">|</span>
      {meta?.total_tokens ? (
        <span>{meta.total_tokens.toLocaleString()} tokens</span>
      ) : (
        <span>~{(cost?.estimated_tokens_input ?? 0) + (cost?.estimated_tokens_output ?? 0)} tokens</span>
      )}
      {displayCost !== undefined && displayCost > 0 && (
        <>
          <span className="text-border">|</span>
          <span className="text-emerald-600 font-medium">
            ¥{((displayCost ?? 0) * 0.073).toFixed(4)}
          </span>
        </>
      )}
    </div>
  );
}

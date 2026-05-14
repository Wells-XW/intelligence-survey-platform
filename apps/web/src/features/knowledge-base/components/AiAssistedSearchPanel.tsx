import { useState } from 'react';
import { Sparkles, Loader2, ChevronUp, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useKnowledgeBaseStore } from '../store';
import { aiAssistedSearch } from '@/lib/api';

export function AiAssistedSearchPanel() {
  const { setAiResult, setIsAiSearching, isAiSearching, aiResult } = useKnowledgeBaseStore();
  const [topic, setTopic] = useState('');
  const [researchQuestion, setResearchQuestion] = useState('');
  const [expanded, setExpanded] = useState(false);

  const handleSearch = async () => {
    if (!topic.trim()) return;
    setIsAiSearching(true);
    try {
      const result = await aiAssistedSearch({
        topic: topic.trim(),
        research_question: researchQuestion.trim() || undefined,
      });
      setAiResult(result);
      setExpanded(true);
    } catch {
      setAiResult(null);
    } finally {
      setIsAiSearching(false);
    }
  };

  return (
    <Card>
      <CardHeader className="pb-3 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />AI 辅助检索
          </CardTitle>
          <Button variant="ghost" size="icon" className="h-6 w-6">
            {expanded ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </Button>
        </div>
      </CardHeader>
      {expanded && (
        <CardContent className="space-y-3">
          <Input
            placeholder="研究主题..."
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
          />
          <Input
            placeholder="研究问题（可选）"
            value={researchQuestion}
            onChange={(e) => setResearchQuestion(e.target.value)}
          />
          <Button
            onClick={handleSearch}
            disabled={!topic.trim() || isAiSearching}
            className="w-full"
            size="sm"
          >
            {isAiSearching ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" />AI 分析中...</> : <><Sparkles className="h-4 w-4 mr-2" />AI 智能搜索</>}
          </Button>

          {aiResult && (
            <div className="bg-muted p-3 rounded text-sm space-y-2 mt-2">
              <p className="text-xs text-muted-foreground">
                模型: {aiResult.model_used} · Token: {aiResult.tokens_used}
              </p>
              <p className="leading-relaxed">{aiResult.ai_summary}</p>
              <div className="flex gap-2 text-xs text-muted-foreground">
                <span>📄 {aiResult.literature_findings.length} 篇文献</span>
                <span>📊 {aiResult.related_scales.length} 个量表</span>
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

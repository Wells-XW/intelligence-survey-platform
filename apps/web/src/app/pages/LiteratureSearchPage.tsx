import { useQuery } from '@tanstack/react-query';
import { BookOpen, Loader2 } from 'lucide-react';
import {
  LiteratureSearchForm,
  SearchResultCard,
  LiteratureDetailPanel,
  AiAssistedSearchPanel,
} from '@/features/knowledge-base/components';
import { useKnowledgeBaseStore } from '@/features/knowledge-base/store';
import { getSavedReferences } from '@/lib/api';

export default function LiteratureSearchPage() {
  const {
    searchResults,
    searchTotal,
    searchCached,
    isSearching,
    selectedResult,
    setSelectedResult,
  } = useKnowledgeBaseStore();

  const { data: savedData, refetch: refetchSaved } = useQuery({
    queryKey: ['saved-references'],
    queryFn: () => getSavedReferences({ limit: 100 }),
    staleTime: 30_000,
  });

  const savedIds = new Set(savedData?.items?.map((r: { external_id?: string; source: string }) => `${r.source}:${r.external_id}`) || []);
  const savedIdMap = new Map(savedData?.items?.map((r: { id: string; external_id?: string; source: string }) => [`${r.source}:${r.external_id}`, r.id]) || []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <BookOpen className="h-6 w-6" />
          文献检索
        </h1>
        <p className="text-muted-foreground mt-1">
          跨 PubMed、Semantic Scholar 搜索学术文献，保存到您的知识库
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <LiteratureSearchForm />

          {isSearching && (
            <div className="flex items-center gap-2 text-muted-foreground py-6 justify-center">
              <Loader2 className="h-5 w-5 animate-spin" />
              <span>正在搜索...</span>
            </div>
          )}

          {!isSearching && searchResults.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-sm text-muted-foreground">
                  找到 {searchTotal} 条结果{searchCached && ' (缓存)'}
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3">
                {searchResults.map((r, i) => {
                  const key = `${r.source}:${r.external_id}`;
                  return (
                    <SearchResultCard
                      key={r.doi || r.title || i}
                      result={r}
                      isSaved={savedIds.has(key)}
                      savedId={savedIdMap.get(key)}
                      onSelect={setSelectedResult}
                      onSave={refetchSaved}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {!isSearching && !searchResults.length && (
            <div className="text-center py-12 text-muted-foreground">
              <BookOpen className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>输入关键词开始搜索学术文献</p>
              <p className="text-xs mt-1">支持 PubMed 和 Semantic Scholar</p>
            </div>
          )}
        </div>

        <div className="space-y-4">
          <AiAssistedSearchPanel />
          <div className="bg-muted/50 rounded-lg p-4 text-sm">
            <h3 className="font-medium mb-2">使用提示</h3>
            <ul className="space-y-1.5 text-muted-foreground">
              <li>• 使用英文关键词搜索 PubMed 效果最佳</li>
              <li>• 中文研究建议尝试 AI 辅助检索</li>
              <li>• 搜索 DOI 可直接定位论文</li>
              <li>• 保存的文献可在知识库页面查看</li>
            </ul>
          </div>
        </div>
      </div>

      {selectedResult && (
        <LiteratureDetailPanel
          result={selectedResult}
          onClose={() => setSelectedResult(null)}
        />
      )}
    </div>
  );
}

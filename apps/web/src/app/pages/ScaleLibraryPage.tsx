import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Library, Search, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  ScaleCard,
  ScaleDetailPanel,
  ScaleImportDialog,
} from '@/features/knowledge-base/components';
import { useKnowledgeBaseStore } from '@/features/knowledge-base/store';
import { searchScales, type ScaleResponse } from '@/lib/api';

const DISCIPLINES = [
  { value: '', label: '全部' },
  { value: 'psychology', label: '心理学' },
  { value: 'sociology', label: '社会学' },
  { value: 'education', label: '教育学' },
  { value: 'management', label: '管理学' },
  { value: 'health', label: '健康' },
];

export default function ScaleLibraryPage() {
  const { scaleResults, scaleTotal, selectedScale, setSelectedScale, scaleDiscipline, setScaleDiscipline, setScales } = useKnowledgeBaseStore();
  const [query, setQuery] = useState('');
  const [isSearching, setIsSearching] = useState(false);
  const [importTarget, setImportTarget] = useState<ScaleResponse | null>(null);

  const handleSearch = async (discipline?: string) => {
    setIsSearching(true);
    try {
      const d = discipline !== undefined ? discipline : scaleDiscipline;
      const data = await searchScales({ query: query || undefined, discipline: d || undefined, limit: 30 });
      setScales(data.results, data.total_count);
    } catch {
      setScales([], 0);
    } finally {
      setIsSearching(false);
    }
  };

  // Load on mount
  const { data: scalesInitialData } = useQuery({
    queryKey: ['scales', scaleDiscipline],
    queryFn: () => searchScales({ discipline: scaleDiscipline || undefined, limit: 30 }),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (scalesInitialData) {
      setScales(scalesInitialData.results, scalesInitialData.total_count);
    }
  }, [scalesInitialData, setScales]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <Library className="h-6 w-6" />
          量表库
        </h1>
        <p className="text-muted-foreground mt-1">
          浏览和搜索经过验证的学术测量量表，一键导入到您的问卷
        </p>
      </div>

      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索量表..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            className="pl-9"
          />
        </div>
        <Button onClick={() => handleSearch()} disabled={isSearching}>
          {isSearching ? <Loader2 className="h-4 w-4 animate-spin" /> : '搜索'}
        </Button>
      </div>

      <div className="flex gap-2 flex-wrap">
        {DISCIPLINES.map((d) => (
          <Button
            key={d.value}
            variant={scaleDiscipline === d.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setScaleDiscipline(d.value);
              handleSearch(d.value);
            }}
          >
            {d.label}
          </Button>
        ))}
      </div>

      {isSearching && (
        <div className="flex items-center gap-2 text-muted-foreground py-6 justify-center">
          <Loader2 className="h-5 w-5 animate-spin" />加载中...
        </div>
      )}

      {!isSearching && (
        <>
          <p className="text-sm text-muted-foreground">共 {scaleTotal} 个量表</p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {scaleResults.map((s) => (
              <ScaleCard
                key={s.id}
                scale={s}
                onSelect={setSelectedScale}
                onImport={setImportTarget}
              />
            ))}
          </div>
          {scaleResults.length === 0 && (
            <div className="text-center py-12 text-muted-foreground">
              <Library className="h-12 w-12 mx-auto mb-3 opacity-30" />
              <p>暂无匹配的量表</p>
            </div>
          )}
        </>
      )}

      {selectedScale && (
        <ScaleDetailPanel
          scale={selectedScale}
          onClose={() => setSelectedScale(null)}
          onImport={setImportTarget}
        />
      )}

      {importTarget && (
        <ScaleImportDialog
          scale={importTarget}
          surveyId=""
          onClose={() => setImportTarget(null)}
        />
      )}
    </div>
  );
}

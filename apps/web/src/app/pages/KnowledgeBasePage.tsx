import { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { GraduationCap, Bookmark, BookOpen } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  KnowledgeEntryCard,
  SavedReferencesList,
} from '@/features/knowledge-base/components';
import { useKnowledgeBaseStore } from '@/features/knowledge-base/store';
import { searchEntries, type KnowledgeEntryResponse } from '@/lib/api';

const TABS = [
  { key: 'saved', label: '已保存文献', icon: Bookmark },
  { key: 'guides', label: '方法学指南', icon: BookOpen },
  { key: 'practices', label: '最佳实践', icon: GraduationCap },
] as const;

type TabKey = typeof TABS[number]['key'];

export default function KnowledgeBasePage() {
  const { entryResults, setEntries, entryCategory, setEntryCategory } = useKnowledgeBaseStore();
  const [activeTab, setActiveTab] = useState<TabKey>('saved');
  const [selectedEntry, setSelectedEntry] = useState<KnowledgeEntryResponse | null>(null);

  const { isLoading: entriesLoading, data: entriesData } = useQuery({
    queryKey: ['entries', entryCategory],
    queryFn: () => searchEntries({ category: entryCategory || undefined, limit: 30 }),
    staleTime: 60_000,
  });

  useEffect(() => {
    if (entriesData) {
      setEntries(entriesData.results, entriesData.total_count);
    }
  }, [entriesData, setEntries]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2">
          <GraduationCap className="h-6 w-6" />
          知识库
        </h1>
        <p className="text-muted-foreground mt-1">
          方法学指南、最佳实践和已保存文献
        </p>
      </div>

      <div className="flex gap-2 border-b pb-2">
        {TABS.map((tab) => {
          const Icon = tab.icon;
          return (
            <Button
              key={tab.key}
              variant={activeTab === tab.key ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setActiveTab(tab.key)}
            >
              <Icon className="h-4 w-4 mr-1.5" />
              {tab.label}
            </Button>
          );
        })}
      </div>

      {activeTab === 'saved' && <SavedReferencesList />}

      {activeTab === 'guides' && (
        <>
          <div className="flex gap-2 flex-wrap">
            {['methodology_guide', 'template', 'glossary'].map((cat) => (
              <Button
                key={cat}
                variant={entryCategory === cat ? 'default' : 'outline'}
                size="sm"
                onClick={() => setEntryCategory(entryCategory === cat ? '' : cat)}
              >
                {cat === 'methodology_guide' ? '指南' : cat === 'template' ? '模板' : '术语'}
              </Button>
            ))}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {entryResults.map((e) => (
              <KnowledgeEntryCard key={e.id} entry={e} onSelect={setSelectedEntry} />
            ))}
          </div>
          {!entriesLoading && entryResults.length === 0 && (
            <p className="text-muted-foreground text-sm py-6 text-center">暂无条目</p>
          )}
        </>
      )}

      {activeTab === 'practices' && (
        <div>
          <div className="flex gap-2 flex-wrap mb-4">
            <Button
              variant={entryCategory === 'best_practice' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setEntryCategory(entryCategory === 'best_practice' ? '' : 'best_practice')}
            >
              最佳实践
            </Button>
            <Button
              variant={entryCategory === 'faq' ? 'default' : 'outline'}
              size="sm"
              onClick={() => setEntryCategory(entryCategory === 'faq' ? '' : 'faq')}
            >
              常见问题
            </Button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {entryResults.map((e) => (
              <KnowledgeEntryCard key={e.id} entry={e} onSelect={setSelectedEntry} />
            ))}
          </div>
        </div>
      )}

      {/* Entry detail modal */}
      {selectedEntry && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setSelectedEntry(null)}>
          <div className="bg-background rounded-lg max-w-2xl w-full mx-4 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="p-6 space-y-4">
              <h3 className="text-xl font-semibold">{selectedEntry.title}</h3>
              {selectedEntry.tags && (
                <div className="flex gap-1 flex-wrap">
                  {selectedEntry.tags.map((t, i) => (
                    <span key={i} className="px-2 py-0.5 bg-secondary rounded text-xs">{t}</span>
                  ))}
                </div>
              )}
              {selectedEntry.content && typeof selectedEntry.content === 'object' && 'sections' in selectedEntry.content && (
                <div className="space-y-4">
                  {(selectedEntry.content.sections as Array<{ heading: string; body: string }>).map((section, i) => (
                    <div key={i}>
                      <h4 className="font-medium mb-1">{section.heading}</h4>
                      <p className="text-sm text-muted-foreground leading-relaxed">{section.body}</p>
                    </div>
                  ))}
                </div>
              )}
              <Button variant="outline" size="sm" onClick={() => setSelectedEntry(null)} className="mt-2">关闭</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

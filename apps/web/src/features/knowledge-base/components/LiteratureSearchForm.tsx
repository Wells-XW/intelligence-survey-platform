import { useState } from 'react';
import { Search } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useKnowledgeBaseStore } from '../store';
import { searchLiterature } from '@/lib/api';

export function LiteratureSearchForm() {
  const { searchQuery, setSearchQuery, searchSource, setSearchSource, setSearchResults, setIsSearching } = useKnowledgeBaseStore();
  const [query, setQuery] = useState(searchQuery);

  const handleSearch = async () => {
    if (!query.trim()) return;
    setSearchQuery(query);
    setIsSearching(true);
    try {
      const data = await searchLiterature({ query: query.trim(), source: searchSource });
      setSearchResults(data);
    } catch (err: unknown) {
      console.error('Literature search failed:', err);
      setSearchResults({ results: [], total_count: 0, source: searchSource, query: query.trim(), cached: false });
    } finally {
      setIsSearching(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索学术文献（关键词 / 作者 / DOI）..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            className="pl-9"
          />
        </div>
        <Button onClick={handleSearch} disabled={!query.trim()}>
          搜索
        </Button>
      </div>
      <div className="flex gap-2 flex-wrap">
        {[
          { value: 'all', label: '全部来源' },
          { value: 'pubmed', label: 'PubMed' },
          { value: 'semantic_scholar', label: 'Semantic Scholar' },
        ].map((s) => (
          <Button
            key={s.value}
            variant={searchSource === s.value ? 'default' : 'outline'}
            size="sm"
            onClick={() => setSearchSource(s.value)}
          >
            {s.label}
          </Button>
        ))}
      </div>
    </div>
  );
}

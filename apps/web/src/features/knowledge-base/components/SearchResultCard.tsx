import { useState } from 'react';
import { Bookmark, BookmarkCheck, ExternalLink, ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { LiteratureResult } from '@/lib/api';
import { saveReference, deleteReference } from '@/lib/api';

interface Props {
  result: LiteratureResult;
  isSaved?: boolean;
  savedId?: string;
  onSelect: (r: LiteratureResult) => void;
  onSave?: () => void;
}

const SOURCE_BADGES: Record<string, { label: string; color: string }> = {
  pubmed: { label: 'PubMed', color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  semantic_scholar: { label: 'Semantic Scholar', color: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400' },
  cnki_web: { label: 'CNKI', color: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400' },
};

export function SearchResultCard({ result, isSaved: initialSaved, savedId, onSelect, onSave }: Props) {
  const [expanded, setExpanded] = useState(false);
  const [saved, setSaved] = useState(initialSaved ?? false);
  const [saving, setSaving] = useState(false);
  const badge = SOURCE_BADGES[result.source] || SOURCE_BADGES.pubmed;

  const handleToggleSave = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setSaving(true);
    try {
      if (saved && savedId) {
        await deleteReference(savedId);
        setSaved(false);
      } else {
        await saveReference({ literature: result });
        setSaved(true);
      }
      onSave?.();
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      className="cursor-pointer hover:shadow-md transition-shadow"
      onClick={() => onSelect(result)}
    >
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-base font-medium leading-snug line-clamp-2">
            {result.title}
          </CardTitle>
          <Button
            variant="ghost"
            size="icon"
            className="shrink-0 h-8 w-8"
            onClick={handleToggleSave}
            disabled={saving}
            title={saved ? '取消保存' : '保存文献'}
          >
            {saved ? <BookmarkCheck className="h-4 w-4 text-primary" /> : <Bookmark className="h-4 w-4" />}
          </Button>
        </div>
        <div className="flex flex-wrap gap-2 text-xs mt-1">
          <span className={badge.color + ' px-2 py-0.5 rounded-full font-medium'}>{badge.label}</span>
          {result.year && <span className="text-muted-foreground">{result.year}</span>}
          {result.journal && <span className="text-muted-foreground truncate max-w-[200px]">{result.journal}</span>}
        </div>
      </CardHeader>
      <CardContent className="text-sm">
        {result.authors.length > 0 && (
          <p className="text-muted-foreground mb-1">{result.authors.slice(0, 3).join(', ')}{result.authors.length > 3 ? ' et al.' : ''}</p>
        )}
        {result.abstract && (
          <div>
            <p className={`text-muted-foreground ${expanded ? '' : 'line-clamp-3'}`}>
              {result.abstract}
            </p>
            {result.abstract.length > 200 && (
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs mt-1 -ml-2"
                onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}
              >
                {expanded ? <><ChevronUp className="h-3 w-3 mr-1" />收起</> : <><ChevronDown className="h-3 w-3 mr-1" />展开</>}
              </Button>
            )}
          </div>
        )}
        <div className="flex gap-3 mt-2 text-xs text-muted-foreground">
          {result.doi && (
            <a href={`https://doi.org/${result.doi}`} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 hover:text-primary"
               onClick={(e) => e.stopPropagation()}>
              <ExternalLink className="h-3 w-3" />DOI
            </a>
          )}
          {result.url && (
            <a href={result.url} target="_blank" rel="noopener noreferrer"
               className="inline-flex items-center gap-1 hover:text-primary"
               onClick={(e) => e.stopPropagation()}>
              <ExternalLink className="h-3 w-3" />原文
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

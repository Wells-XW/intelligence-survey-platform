import { X, Copy, Check } from 'lucide-react';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import type { LiteratureResult } from '@/lib/api';

interface Props {
  result: LiteratureResult | null;
  onClose: () => void;
}

function formatAPA(result: LiteratureResult): string {
  const authors = result.authors.length > 0
    ? result.authors.join(', ')
    : '(未知作者)';
  const year = result.year ? ` (${result.year}).` : ' (n.d.).';
  const title = `${result.title}.`;
  const journal = result.journal ? ` ${result.journal}.` : '';
  const doi = result.doi ? ` https://doi.org/${result.doi}` : '';
  return `${authors}${year} ${title}${journal}${doi}`;
}

function formatGB(result: LiteratureResult): string {
  const authors = result.authors.length > 0
    ? result.authors.join(', ')
    : '佚名.';
  const year = result.year ? `[${result.year}]` : '[n.d.]';
  const title = result.title;
  const journal = result.journal ? `[J] ${result.journal}.` : '';
  const doi = result.doi ? ` DOI:${result.doi}` : '';
  return `${authors}${year} ${title}${journal}${doi}`;
}

export function LiteratureDetailPanel({ result, onClose }: Props) {
  const [format, setFormat] = useState<'apa' | 'gb'>('apa');
  const [copied, setCopied] = useState(false);

  if (!result) return null;

  const citation = format === 'apa' ? formatAPA(result) : formatGB(result);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(citation);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="fixed inset-y-0 right-0 w-full max-w-lg bg-background border-l shadow-xl z-50 overflow-y-auto">
      <div className="sticky top-0 bg-background border-b p-4 flex items-center justify-between">
        <h3 className="font-semibold text-lg">文献详情</h3>
        <Button variant="ghost" size="icon" onClick={onClose}>
          <X className="h-5 w-5" />
        </Button>
      </div>
      <div className="p-6 space-y-5">
        <div>
          <h4 className="text-xl font-semibold leading-relaxed">{result.title}</h4>
        </div>

        <div>
          <p className="text-sm font-medium text-muted-foreground mb-1">作者</p>
          <p>{result.authors.join('、')}</p>
        </div>

        {result.journal && (
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-1">期刊</p>
            <p>{result.journal}{result.year ? ` (${result.year})` : ''}</p>
          </div>
        )}

        {result.abstract && (
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-1">摘要</p>
            <p className="text-sm leading-relaxed text-muted-foreground">{result.abstract}</p>
          </div>
        )}

        {result.keywords && result.keywords.length > 0 && (
          <div>
            <p className="text-sm font-medium text-muted-foreground mb-1">关键词</p>
            <div className="flex flex-wrap gap-1">
              {result.keywords.map((kw, i) => (
                <span key={i} className="px-2 py-0.5 bg-secondary rounded text-xs">{kw}</span>
              ))}
            </div>
          </div>
        )}

        <div>
          <div className="flex items-center justify-between mb-1">
            <p className="text-sm font-medium text-muted-foreground">引用</p>
            <div className="flex gap-1">
              <Button size="sm" variant={format === 'apa' ? 'secondary' : 'ghost'} className="h-7 text-xs" onClick={() => setFormat('apa')}>APA</Button>
              <Button size="sm" variant={format === 'gb' ? 'secondary' : 'ghost'} className="h-7 text-xs" onClick={() => setFormat('gb')}>GB/T</Button>
              <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={handleCopy}>
                {copied ? <Check className="h-3 w-3 text-green-500" /> : <Copy className="h-3 w-3" />}
              </Button>
            </div>
          </div>
          <pre className="bg-muted p-3 rounded text-xs whitespace-pre-wrap font-mono">{citation}</pre>
        </div>

        <div className="flex gap-2">
          {result.doi && (
            <a href={`https://doi.org/${result.doi}`} target="_blank" rel="noopener noreferrer">
              <Button variant="outline" size="sm">DOI 原文</Button>
            </a>
          )}
          {result.url && (
            <a href={result.url} target="_blank" rel="noopener noreferrer">
              <Button variant="outline" size="sm">查看原文</Button>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

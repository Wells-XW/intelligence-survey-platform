import { BookOpen, Lightbulb, FileText, Tag, MessageCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { KnowledgeEntryResponse } from '@/lib/api';

interface Props {
  entry: KnowledgeEntryResponse;
  onSelect: (e: KnowledgeEntryResponse) => void;
}

const CATEGORY_ICONS: Record<string, React.ElementType> = {
  methodology_guide: BookOpen,
  best_practice: Lightbulb,
  template: FileText,
  glossary: Tag,
  faq: MessageCircle,
};

const CATEGORY_LABELS: Record<string, string> = {
  methodology_guide: '方法学指南',
  best_practice: '最佳实践',
  template: '模板',
  glossary: '术语表',
  faq: '常见问题',
};

export function KnowledgeEntryCard({ entry, onSelect }: Props) {
  const Icon = CATEGORY_ICONS[entry.category] || BookOpen;

  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={() => onSelect(entry)}>
      <CardHeader className="pb-2">
        <div className="flex items-start gap-2">
          <Icon className="h-5 w-5 text-primary shrink-0 mt-0.5" />
          <div>
            <CardTitle className="text-base font-medium">{entry.title}</CardTitle>
            <span className="text-xs text-muted-foreground">
              {CATEGORY_LABELS[entry.category] || entry.category}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {entry.tags && entry.tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {entry.tags.map((t, i) => (
              <span key={i} className="px-2 py-0.5 bg-secondary rounded-full text-xs">{t}</span>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

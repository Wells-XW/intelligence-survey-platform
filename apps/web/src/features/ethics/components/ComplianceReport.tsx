import { Card, CardContent } from '@/components/ui/card';
import { FileText } from 'lucide-react';

interface ComplianceReportProps {
  reportMarkdown: string;
  surveyTitle: string;
  generatedAt: string;
}

export function ComplianceReport({
  reportMarkdown,
  surveyTitle,
  generatedAt,
}: ComplianceReportProps) {
  return (
    <Card>
      <CardContent className="p-6">
        <div className="mb-4 flex items-center gap-2 text-sm text-muted-foreground">
          <FileText className="h-4 w-4" />
          <span>报告生成于 {new Date(generatedAt).toLocaleString('zh-CN')}</span>
        </div>
        <div className="prose prose-sm max-w-none prose-headings:font-semibold prose-h1:text-xl prose-h2:text-lg prose-h3:text-base">
          {/* Simple markdown rendering — converts basic syntax */}
          {reportMarkdown.split('\n').map((line, i) => {
            if (line.startsWith('# ')) {
              return (
                <h1 key={i} className="mb-4 text-xl font-bold">
                  {line.slice(2)}
                </h1>
              );
            }
            if (line.startsWith('## ')) {
              return (
                <h2 key={i} className="mb-2 mt-6 text-lg font-semibold">
                  {line.slice(3)}
                </h2>
              );
            }
            if (line.startsWith('### ')) {
              return (
                <h3 key={i} className="mb-2 mt-4 text-base font-medium">
                  {line.slice(4)}
                </h3>
              );
            }
            if (line.startsWith('---')) {
              return <hr key={i} className="my-4" />;
            }
            if (line.startsWith('- ') || line.startsWith('* ')) {
              const content = line.slice(2);
              const isBold = content.startsWith('**');
              return (
                <div key={i} className="ml-4 flex items-start gap-2 text-sm">
                  <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-muted-foreground" />
                  <span>{content}</span>
                </div>
              );
            }
            if (line.startsWith('> ')) {
              return (
                <blockquote key={i} className="ml-4 border-l-2 border-muted pl-3 text-sm italic text-muted-foreground">
                  {line.slice(2)}
                </blockquote>
              );
            }
            if (line.trim() === '') {
              return <div key={i} className="h-2" />;
            }
            return (
              <p key={i} className="text-sm">
                {line}
              </p>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

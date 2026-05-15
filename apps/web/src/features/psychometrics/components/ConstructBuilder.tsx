import { Plus, Trash2, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { usePsychometricsStore } from '../store';

interface Props {
  onAnalyze?: (constructs: Array<{ name: string; items: string[] }>) => void;
  isAnalyzing?: boolean;
}

export function ConstructBuilder({ onAnalyze, isAnalyzing }: Props) {
  const {
    availableItems,
    constructs,
    addConstruct,
    removeConstruct,
    addItemToConstruct,
    removeItemFromConstruct,
  } = usePsychometricsStore();

  // Items not yet assigned to any construct
  const assignedItems = new Set(constructs.flatMap((c) => c.items));
  const unassignedItems = availableItems.filter((a) => !assignedItems.has(a.name));

  return (
    <div className="grid grid-cols-3 gap-4">
      {/* Left: Available Items */}
      <Card className="col-span-1">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">可用题项</CardTitle>
          <p className="text-xs text-muted-foreground">
            {unassignedItems.length} 个未分配
          </p>
        </CardHeader>
        <CardContent className="space-y-1 max-h-96 overflow-y-auto">
          {unassignedItems.length === 0 && (
            <p className="text-xs text-muted-foreground">所有题项已分配</p>
          )}
          {unassignedItems.map((item) => (
            <div
              key={item.name}
              className="flex items-center justify-between rounded border border-border p-2 text-xs hover:bg-muted"
            >
              <div>
                <p className="font-mono font-medium">{item.name}</p>
                <p className="text-muted-foreground truncate max-w-[160px]">{item.title}</p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Center: Constructs */}
      <Card className="col-span-2">
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">构念定义</CardTitle>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                const idx = constructs.length + 1;
                addConstruct(`构念 ${idx}`);
              }}
            >
              <Plus className="h-3 w-3 mr-1" />
              添加构念
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {constructs.length === 0 && (
            <div className="text-center py-6 text-muted-foreground text-sm">
              点击「添加构念」定义潜变量，然后将题项分配到各构念
            </div>
          )}
          {constructs.map((construct, ci) => (
            <div key={construct.name} className="rounded border border-border p-3">
              <div className="flex items-center gap-2 mb-2">
                <Input
                  className="h-7 text-sm font-medium flex-1"
                  value={construct.name}
                  onChange={(e) => {
                    const updated = [...constructs];
                    updated[ci] = { ...construct, name: e.target.value };
                    usePsychometricsStore.setState({ constructs: updated });
                  }}
                />
                <Badge variant="secondary">
                  {construct.items.length} 题项
                </Badge>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 text-red-500 hover:text-red-700"
                  onClick={() => removeConstruct(construct.name)}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              </div>
              {/* Current items in this construct */}
              <div className="space-y-1">
                {construct.items.length === 0 && (
                  <p className="text-xs text-muted-foreground">
                    点击左侧题项添加到本构念
                  </p>
                )}
                {construct.items.map((itemName) => {
                  const itemDef = availableItems.find((a) => a.name === itemName);
                  return (
                    <div
                      key={itemName}
                      className="flex items-center justify-between rounded bg-muted p-1.5 text-xs"
                    >
                      <div>
                        <span className="font-mono">{itemName}</span>
                        {itemDef && (
                          <span className="text-muted-foreground ml-2">
                            {itemDef.title}
                          </span>
                        )}
                      </div>
                      <Button
                        size="icon"
                        variant="ghost"
                        className="h-5 w-5 text-muted-foreground hover:text-red-500"
                        onClick={() => removeItemFromConstruct(construct.name, itemName)}
                      >
                        <Trash2 className="h-3 w-3" />
                      </Button>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      {/* Analyze button */}
      {constructs.length > 0 && (
        <div className="col-span-3 flex justify-end">
          <Button onClick={() => onAnalyze?.(constructs)} disabled={isAnalyzing}>
            <ArrowRight className="h-4 w-4 mr-1" />
            {isAnalyzing ? '分析中…' : '分析构念'}
          </Button>
        </div>
      )}
    </div>
  );
}

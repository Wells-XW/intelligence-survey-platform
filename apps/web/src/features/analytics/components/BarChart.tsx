import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { BarChart as EBarChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  EBarChart,
  GridComponent,
  TooltipComponent,
  TitleComponent,
  LegendComponent,
  CanvasRenderer,
]);

interface BarChartProps {
  title?: string;
  data: Array<{ label: string; value: number }>;
  xLabel?: string;
  yLabel?: string;
  height?: number;
  horizontal?: boolean;
  color?: string;
}

export function BarChart({
  title,
  data,
  xLabel,
  yLabel,
  height = 300,
  horizontal = false,
  color = '#5470c6',
}: BarChartProps) {
  const option = {
    title: title ? { text: title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
    tooltip: { trigger: horizontal ? 'yAxis' : 'xAxis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    [horizontal ? 'yAxis' : 'xAxis']: {
      type: 'category',
      data: data.map((d) => d.label),
      axisLabel: { fontSize: 11, rotate: horizontal ? 0 : data.length > 6 ? 30 : 0 },
    },
    [horizontal ? 'xAxis' : 'yAxis']: {
      type: 'value',
      name: horizontal ? xLabel : yLabel,
      nameTextStyle: { fontSize: 11 },
    },
    series: [
      {
        type: 'bar',
        data: data.map((d) => d.value),
        itemStyle: { color },
        barMaxWidth: 60,
        label: {
          show: true,
          position: horizontal ? 'right' : 'top',
          fontSize: 10,
        },
      },
    ],
  };

  return (
    <ReactEChartsCore
      echarts={echarts}
      option={option}
      style={{ height, width: '100%' }}
      notMerge
    />
  );
}

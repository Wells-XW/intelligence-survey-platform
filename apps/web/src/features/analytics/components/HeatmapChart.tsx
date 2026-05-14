import ReactEChartsCore from 'echarts-for-react/lib/core';
import * as echarts from 'echarts/core';
import { HeatmapChart as EHeatmapChart } from 'echarts/charts';
import {
  TooltipComponent,
  TitleComponent,
  VisualMapComponent,
  GridComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  EHeatmapChart,
  TooltipComponent,
  TitleComponent,
  VisualMapComponent,
  GridComponent,
  CanvasRenderer,
]);

interface HeatmapChartProps {
  title?: string;
  xLabels: string[];
  yLabels: string[];
  data: number[][]; // yLabels.length x xLabels.length
  height?: number;
}

export function HeatmapChart({
  title,
  xLabels,
  yLabels,
  data: matrix,
  height = 400,
}: HeatmapChartProps) {
  // Convert matrix to ECharts heatmap format: [xIdx, yIdx, value]
  const heatData: [number, number, number][] = [];
  for (let y = 0; y < matrix.length; y++) {
    for (let x = 0; x < (matrix[y]?.length ?? 0); x++) {
      heatData.push([x, y, matrix[y][x]]);
    }
  }

  const option = {
    title: title ? { text: title, left: 'center', textStyle: { fontSize: 14 } } : undefined,
    tooltip: {
      formatter: (params: { data: [number, number, number] }) => {
        const [x, y, v] = params.data;
        return `${xLabels[x]} × ${yLabels[y]}<br/>计数: ${v}`;
      },
    },
    grid: { left: 120, right: 60, bottom: 80, top: title ? 60 : 30 },
    xAxis: {
      type: 'category',
      data: xLabels,
      splitArea: { show: true },
      axisLabel: { fontSize: 10, rotate: xLabels.length > 6 ? 30 : 0 },
    },
    yAxis: {
      type: 'category',
      data: yLabels,
      splitArea: { show: true },
      axisLabel: { fontSize: 11 },
    },
    visualMap: {
      min: 0,
      max: Math.max(...heatData.map((d) => d[2]), 1),
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#f0f0f0', '#5470c6', '#1a237e'] },
    },
    series: [
      {
        type: 'heatmap',
        data: heatData,
        label: { show: true, fontSize: 11 },
        emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } },
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

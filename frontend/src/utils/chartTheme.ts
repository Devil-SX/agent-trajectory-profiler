export const CHART_COLORS = {
  user: 'var(--chart-user)',
  model: 'var(--chart-model)',
  tool: 'var(--chart-tool)',
  inactive: 'var(--chart-inactive)',
  input: 'var(--chart-input)',
  output: 'var(--chart-output)',
  cache: 'var(--chart-cache)',
  warning: 'var(--chart-warning)',
  danger: 'var(--chart-danger)',
  compareA: 'var(--chart-compare-a)',
  compareB: 'var(--chart-compare-b)',
} as const;

export const CHART_DISTRIBUTION_COLORS = [
  CHART_COLORS.compareA,
  CHART_COLORS.compareB,
  CHART_COLORS.tool,
  CHART_COLORS.danger,
  CHART_COLORS.model,
  CHART_COLORS.inactive,
] as const;

export const CHART_GRID_PROPS = {
  stroke: 'var(--chart-grid)',
  strokeDasharray: '3 3',
} as const;

export const CHART_AXIS_PROPS = {
  tick: { fill: 'var(--color-text-muted)', fontSize: 12 },
  axisLine: { stroke: 'var(--color-border)' },
  tickLine: { stroke: 'var(--color-border)' },
} as const;

export const CHART_LEGEND_PROPS = {
  wrapperStyle: {
    color: 'var(--color-text-secondary)',
    fontSize: '12px',
  },
} as const;

export const CHART_TOOLTIP_STYLE = {
  backgroundColor: 'var(--chart-tooltip-bg)',
  border: '1px solid var(--chart-tooltip-border)',
  borderRadius: '8px',
  color: 'var(--chart-tooltip-text)',
} as const;

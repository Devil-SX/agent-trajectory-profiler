/**
 * TimeBreakdownChart component visualizes session time distribution.
 *
 * Shows how time is allocated across:
 * - Model (inference latency)
 * - Tool (execution time)
 * - User (human response time)
 * - Inactive (idle time >30min)
 *
 * Renders as horizontal stacked bar chart and active-time-only pie chart.
 */

import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { TimeBreakdown } from '../types/session';
import './TimeBreakdownChart.css';

interface TimeBreakdownChartProps {
  timeBreakdown: TimeBreakdown | null | undefined;
  showPieChart?: boolean;
  showBarChart?: boolean;
}

interface PieTooltipData {
  name: string;
  value: number;
  percent: number;
}

interface PieTooltipProps {
  active?: boolean;
  payload?: Array<{ payload: PieTooltipData }>;
}

const COLORS = {
  model: '#ef4444',    // Red - high priority
  tool: '#f97316',     // Orange - medium priority
  user: '#22c55e',     // Green - low latency
  inactive: '#6b7280', // Gray - neutral
};

const formatTime = (seconds: number): string => {
  if (seconds === 0) return '0s';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  if (secs > 0 || parts.length === 0) parts.push(`${secs}s`);

  return parts.join(' ');
};

function CustomPieTooltip({ active, payload }: PieTooltipProps) {
  if (!active || !payload || payload.length === 0) {
    return null;
  }

  const data = payload[0].payload;
  return (
    <div className="custom-tooltip">
      <p className="label">{data.name}</p>
      <p className="value">
        <strong>{formatTime(data.value)}</strong>
      </p>
      <p className="percent">{data.percent.toFixed(1)}%</p>
    </div>
  );
}

export function TimeBreakdownChart({
  timeBreakdown,
  showPieChart = true,
  showBarChart = true,
}: TimeBreakdownChartProps) {
  if (!timeBreakdown) {
    return (
      <div className="time-breakdown-chart empty">
        <p>No time breakdown data available</p>
      </div>
    );
  }

  const totalSpanTime = timeBreakdown.total_active_time_seconds + timeBreakdown.total_inactive_time_seconds;
  const computedActiveRatio = totalSpanTime > 0
    ? timeBreakdown.total_active_time_seconds / totalSpanTime
    : 0;
  const activeTimeRatio = typeof timeBreakdown.active_time_ratio === 'number'
    ? timeBreakdown.active_time_ratio
    : computedActiveRatio;
  const activeTimeRatioPercent = activeTimeRatio * 100;

  // Prepare data for stacked bar chart
  const barData = [
    {
      name: 'Time Distribution',
      Model: timeBreakdown.model_time_percent,
      Tool: timeBreakdown.tool_time_percent,
      User: timeBreakdown.user_time_percent,
      Inactive: timeBreakdown.inactive_time_percent,
    },
  ];

  // Prepare data for pie chart
  const pieData = [
    {
      name: 'Model',
      value: timeBreakdown.total_model_time_seconds,
      percent: timeBreakdown.model_time_percent,
      color: COLORS.model,
    },
    {
      name: 'Tool',
      value: timeBreakdown.total_tool_time_seconds,
      percent: timeBreakdown.tool_time_percent,
      color: COLORS.tool,
    },
    {
      name: 'User',
      value: timeBreakdown.total_user_time_seconds,
      percent: timeBreakdown.user_time_percent,
      color: COLORS.user,
    },
  ].filter((item) => item.value > 0); // Only show non-zero categories

  const categoryCards = [
    {
      label: 'Model',
      time: timeBreakdown.total_model_time_seconds,
      percent: timeBreakdown.model_time_percent,
      color: COLORS.model,
    },
    {
      label: 'Tool',
      time: timeBreakdown.total_tool_time_seconds,
      percent: timeBreakdown.tool_time_percent,
      color: COLORS.tool,
    },
    {
      label: 'User',
      time: timeBreakdown.total_user_time_seconds,
      percent: timeBreakdown.user_time_percent,
      color: COLORS.user,
    },
  ];

  const renderCustomLabel = ({
    cx,
    cy,
    midAngle,
    innerRadius,
    outerRadius,
    percent,
  }: {
    cx?: number;
    cy?: number;
    midAngle?: number;
    innerRadius?: number;
    outerRadius?: number;
    percent?: number;
  }) => {
    // Guard clause to handle undefined values from Recharts
    if (cx === undefined || cy === undefined || midAngle === undefined ||
        innerRadius === undefined || outerRadius === undefined || percent === undefined) {
      return null;
    }

    const RADIAN = Math.PI / 180;
    const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
    const x = cx + radius * Math.cos(-midAngle * RADIAN);
    const y = cy + radius * Math.sin(-midAngle * RADIAN);

    if (percent < 0.05) return null; // Don't show label for <5%

    return (
      <text
        x={x}
        y={y}
        fill="white"
        textAnchor={x > cx ? 'start' : 'end'}
        dominantBaseline="central"
        className="pie-label"
      >
        {`${(percent * 100).toFixed(1)}%`}
      </text>
    );
  };

  return (
    <div className="time-breakdown-chart">
      <div className="chart-header">
        <h3>Time Distribution</h3>
        <p className="subtitle">
          Active: {formatTime(timeBreakdown.total_active_time_seconds)} |
          Inactive: {formatTime(timeBreakdown.total_inactive_time_seconds)}
        </p>
        <p className="subtitle active-ratio-text">
          Active ratio: {activeTimeRatioPercent.toFixed(1)}%
        </p>
      </div>

      <div className="time-category-grid">
        {categoryCards.map((item) => (
          <article key={item.label} className="time-category-card">
            <h4>
              <span className="legend-color" style={{ backgroundColor: item.color }}></span>
              {item.label}
            </h4>
            <p className="time-value">{formatTime(item.time)}</p>
            <p className="time-percent">{item.percent.toFixed(1)}% of active time</p>
          </article>
        ))}
      </div>

      <div className="charts-container">
        {showBarChart && (
          <div className="bar-chart-section">
            <ResponsiveContainer width="100%" height={80}>
              <BarChart
                data={barData}
                layout="vertical"
                margin={{ top: 5, right: 30, left: 20, bottom: 5 }}
              >
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" domain={[0, 100]} unit="%" />
                <YAxis type="category" dataKey="name" width={120} />
                <Tooltip
                  formatter={(value: number | undefined) => value !== undefined ? `${value.toFixed(1)}%` : 'N/A'}
                  contentStyle={{
                    backgroundColor: '#333',
                    border: '1px solid #555',
                    borderRadius: '4px',
                    color: '#fff',
                  }}
                />
                <Legend />
                <Bar dataKey="Model" stackId="a" fill={COLORS.model} />
                <Bar dataKey="Tool" stackId="a" fill={COLORS.tool} />
                <Bar dataKey="User" stackId="a" fill={COLORS.user} />
                <Bar dataKey="Inactive" stackId="a" fill={COLORS.inactive} />
              </BarChart>
            </ResponsiveContainer>

            <div className="time-legend">
              <div className="legend-item">
                <span className="legend-color" style={{ backgroundColor: COLORS.model }}></span>
                <span>Model: {formatTime(timeBreakdown.total_model_time_seconds)}</span>
              </div>
              <div className="legend-item">
                <span className="legend-color" style={{ backgroundColor: COLORS.tool }}></span>
                <span>Tool: {formatTime(timeBreakdown.total_tool_time_seconds)}</span>
              </div>
              <div className="legend-item">
                <span className="legend-color" style={{ backgroundColor: COLORS.user }}></span>
                <span>User: {formatTime(timeBreakdown.total_user_time_seconds)}</span>
              </div>
              {timeBreakdown.total_inactive_time_seconds > 0 && (
                <div className="legend-item">
                  <span className="legend-color" style={{ backgroundColor: COLORS.inactive }}></span>
                  <span>Inactive: {formatTime(timeBreakdown.total_inactive_time_seconds)}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {showPieChart && pieData.length > 0 && (
          <div className="pie-chart-section">
            <p className="pie-scope-note">Pie chart scope: active time only (Model/Tool/User).</p>
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  labelLine={false}
                  label={renderCustomLabel}
                  outerRadius={100}
                  fill="#8884d8"
                  dataKey="value"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip content={<CustomPieTooltip />} />
              </PieChart>
            </ResponsiveContainer>
            <div className="pie-scope-list" aria-label="Pie categories">
              {pieData.map((entry) => (
                <span key={entry.name} className="pie-scope-item">
                  {entry.name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

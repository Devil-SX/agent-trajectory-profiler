/**
 * MetricComparison component displays a side-by-side comparison of two sessions.
 *
 * Features:
 * - Dual-column layout for comparing Session A and Session B
 * - Compares 4 key metrics: Total Tokens, Automation Ratio, Duration, Bottleneck
 * - Bar charts using Recharts for visual comparison
 * - Highlights large differences (>20% threshold) with yellow background
 * - Graceful handling of null/missing statistics
 */

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { SessionStatistics } from '../types/session';
import { formatTokenCount } from '../utils/tokenFormat';
import {
  createTimeAxisTickFormatter,
  formatTokenAxisTick,
  formatTokenWithRawValue,
} from '../utils/chartFormatters';
import './MetricComparison.css';

interface MetricComparisonProps {
  /** Session ID for session A - used for context in parent component */
  sessionAId: string;
  /** Session ID for session B - used for context in parent component */
  sessionBId: string;
  statisticsA: SessionStatistics | null;
  statisticsB: SessionStatistics | null;
}

interface DiffResult {
  value: number;
  percent: number;
  isLarge: boolean;
}

const BOTTLENECK_COLORS: Record<string, string> = {
  Model: '#ef4444',
  Tool: '#f97316',
  User: '#22c55e',
};

const calculateDiff = (a: number, b: number): DiffResult => {
  const diff = b - a;
  const percent = a !== 0 ? (diff / a) * 100 : 0;
  const isLarge = Math.abs(percent) > 20;
  return { value: diff, percent, isLarge };
};

const calculateAutomationRatio = (stats: SessionStatistics | null): number | null => {
  if (!stats) return null;
  if (stats.user_message_count === 0) return null;
  return stats.total_tool_calls / stats.user_message_count;
};

const getBottleneckType = (stats: SessionStatistics | null): string | null => {
  if (!stats || !stats.time_breakdown) return null;

  const tb = stats.time_breakdown;
  if (tb.user_interaction_count === 0) return 'Model';

  if (
    tb.model_time_percent > tb.tool_time_percent &&
    tb.model_time_percent > tb.user_time_percent
  ) {
    return 'Model';
  }
  if (tb.tool_time_percent > tb.user_time_percent) {
    return 'Tool';
  }
  return 'User';
};

const formatDuration = (seconds: number | null): string => {
  if (seconds === null || seconds === undefined) return 'N/A';

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
};

export function MetricComparison({
  statisticsA,
  statisticsB,
}: MetricComparisonProps) {
  // Handle null statistics
  if (!statisticsA || !statisticsB) {
    return (
      <div className="metric-comparison-container">
        <div className="metric-comparison__empty">
          <p>No statistics available for comparison</p>
        </div>
      </div>
    );
  }

  // Calculate metrics
  const tokensA = statisticsA.total_tokens;
  const tokensB = statisticsB.total_tokens;
  const tokensDiff = calculateDiff(tokensA, tokensB);

  const automationA = calculateAutomationRatio(statisticsA) ?? 0;
  const automationB = calculateAutomationRatio(statisticsB) ?? 0;
  const automationDiff = calculateDiff(automationA, automationB);

  const durationA = statisticsA.session_duration_seconds;
  const durationB = statisticsB.session_duration_seconds;
  const durationDiff =
    durationA && durationB ? calculateDiff(durationA, durationB) : { value: 0, percent: 0, isLarge: false };
  const durationAxisTickFormatter = createTimeAxisTickFormatter(
    Math.max(Math.abs(durationA ?? 0), Math.abs(durationB ?? 0))
  );

  const bottleneckA = getBottleneckType(statisticsA);
  const bottleneckB = getBottleneckType(statisticsB);
  const bottleneckMatch = bottleneckA === bottleneckB;

  return (
    <div className="metric-comparison-container">
      {/* Tokens Metric */}
      <div className={`comparison-metric ${tokensDiff.isLarge ? 'comparison-metric--highlight' : ''}`}>
        <h3 className="comparison-metric__title">Total Tokens</h3>
        <div className="comparison-metric__content">
          <div className="comparison-column comparison-column--a">
            <div className="comparison-column__label">Session A</div>
            <div className="comparison-column__value" title={tokensA.toLocaleString()}>
              {formatTokenCount(tokensA)}
            </div>
          </div>
          <div className="comparison-column comparison-column--b">
            <div className="comparison-column__label">Session B</div>
            <div className="comparison-column__value" title={tokensB.toLocaleString()}>
              {formatTokenCount(tokensB)}
            </div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart
            data={[
              { name: 'Session A', tokens: tokensA },
              { name: 'Session B', tokens: tokensB },
            ]}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" />
            <YAxis tickFormatter={formatTokenAxisTick} />
            <Tooltip
              formatter={(value: number | undefined) =>
                value !== undefined ? formatTokenWithRawValue(value) : 'N/A'
              }
            />
            <Bar dataKey="tokens" fill="#3b82f6" />
          </BarChart>
        </ResponsiveContainer>
        {tokensDiff.isLarge && (
          <div className="comparison-metric__diff">
            Difference: {tokensDiff.percent > 0 ? '+' : ''}{tokensDiff.percent.toFixed(1)}%
          </div>
        )}
      </div>

      {/* Automation Ratio Metric */}
      <div className={`comparison-metric ${automationDiff.isLarge ? 'comparison-metric--highlight' : ''}`}>
        <h3 className="comparison-metric__title">Automation Ratio</h3>
        <div className="comparison-metric__content">
          <div className="comparison-column comparison-column--a">
            <div className="comparison-column__label">Session A</div>
            <div className="comparison-column__value">{automationA.toFixed(2)}x</div>
          </div>
          <div className="comparison-column comparison-column--b">
            <div className="comparison-column__label">Session B</div>
            <div className="comparison-column__value">{automationB.toFixed(2)}x</div>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={120}>
          <BarChart
            data={[
              { name: 'Session A', ratio: automationA },
              { name: 'Session B', ratio: automationB },
            ]}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="name" />
            <YAxis />
            <Tooltip formatter={(value: number | undefined) => (value !== undefined ? value.toFixed(2) : 'N/A')} />
            <Bar dataKey="ratio" fill="#10b981" />
          </BarChart>
        </ResponsiveContainer>
        {automationDiff.isLarge && (
          <div className="comparison-metric__diff">
            Difference: {automationDiff.percent > 0 ? '+' : ''}{automationDiff.percent.toFixed(1)}%
          </div>
        )}
      </div>

      {/* Duration Metric */}
      <div className={`comparison-metric ${durationDiff.isLarge ? 'comparison-metric--highlight' : ''}`}>
        <h3 className="comparison-metric__title">Session Duration</h3>
        <div className="comparison-metric__content">
          <div className="comparison-column comparison-column--a">
            <div className="comparison-column__label">Session A</div>
            <div className="comparison-column__value">{formatDuration(durationA)}</div>
          </div>
          <div className="comparison-column comparison-column--b">
            <div className="comparison-column__label">Session B</div>
            <div className="comparison-column__value">{formatDuration(durationB)}</div>
          </div>
        </div>
        {durationA !== null && durationB !== null && (
          <>
            <ResponsiveContainer width="100%" height={120}>
              <BarChart
                data={[
                  { name: 'Session A', duration: durationA },
                  { name: 'Session B', duration: durationB },
                ]}
              >
                <CartesianGrid strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="name" />
                <YAxis tickFormatter={durationAxisTickFormatter} />
                <Tooltip
                  formatter={(value: number | undefined) =>
                    value !== undefined
                      ? `${durationAxisTickFormatter(value)} (${formatDuration(value)})`
                      : 'N/A'
                  }
                />
                <Bar dataKey="duration" fill="#f59e0b" />
              </BarChart>
            </ResponsiveContainer>
            {durationDiff.isLarge && (
              <div className="comparison-metric__diff">
                Difference: {durationDiff.percent > 0 ? '+' : ''}{durationDiff.percent.toFixed(1)}%
              </div>
            )}
          </>
        )}
      </div>

      {/* Bottleneck Metric */}
      <div className={`comparison-metric ${!bottleneckMatch ? 'comparison-metric--highlight' : ''}`}>
        <h3 className="comparison-metric__title">Bottleneck Analysis</h3>
        <div className="comparison-metric__content">
          <div className="comparison-column comparison-column--a">
            <div className="comparison-column__label">Session A</div>
            {bottleneckA ? (
              <div
                className="comparison-bottleneck-badge"
                style={{
                  borderColor: BOTTLENECK_COLORS[bottleneckA] || '#6b7280',
                  backgroundColor: BOTTLENECK_COLORS[bottleneckA] || '#6b7280',
                }}
              >
                {bottleneckA}
              </div>
            ) : (
              <div className="comparison-column__value">N/A</div>
            )}
          </div>
          <div className="comparison-column comparison-column--b">
            <div className="comparison-column__label">Session B</div>
            {bottleneckB ? (
              <div
                className="comparison-bottleneck-badge"
                style={{
                  borderColor: BOTTLENECK_COLORS[bottleneckB] || '#6b7280',
                  backgroundColor: BOTTLENECK_COLORS[bottleneckB] || '#6b7280',
                }}
              >
                {bottleneckB}
              </div>
            ) : (
              <div className="comparison-column__value">N/A</div>
            )}
          </div>
        </div>
        {!bottleneckMatch && (
          <div className="comparison-metric__diff">Different bottlenecks detected</div>
        )}
      </div>
    </div>
  );
}

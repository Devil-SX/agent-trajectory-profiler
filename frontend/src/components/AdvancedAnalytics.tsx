/**
 * AdvancedAnalytics component for displaying advanced session analytics.
 *
 * Features:
 * - Token usage heatmap over time
 * - Expensive operations highlighting
 * - Tool usage patterns analysis
 * - Subagent efficiency metrics
 * - Session comparison (when multiple sessions selected)
 * - Export to CSV/JSON
 * - Performance bottleneck identification
 * - Usage-based recommendations
 */

import { useEffect, useState, useMemo } from 'react';
import toast from 'react-hot-toast';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Area,
  AreaChart,
} from 'recharts';
import { useSessionDetailQuery, useSessionStatisticsQuery } from '../hooks/useSessionsQuery';
import {
  computeAdvancedAnalytics,
  compareSessions,
} from '../utils/analyticsComputer';
import {
  exportData,
  downloadFiles,
} from '../utils/exportData';
import { formatTokenCount } from '../utils/tokenFormat';
import { formatTokenAxisTick, formatTokenWithRawValue } from '../utils/chartFormatters';
import {
  CHART_AXIS_PROPS,
  CHART_COLORS,
  CHART_GRID_PROPS,
  CHART_LEGEND_PROPS,
  CHART_TOOLTIP_STYLE,
} from '../utils/chartTheme';
import type { ExportConfig } from '../types/analytics';
import { useI18n } from '../i18n';

import { MetricComparison } from './MetricComparison';
import { CrossSessionOverview } from './CrossSessionOverview';
import './AdvancedAnalytics.css';

interface AdvancedAnalyticsProps {
  sessionId: string | null;
  comparisonSessionId?: string | null;
}

export function AdvancedAnalytics({ sessionId, comparisonSessionId }: AdvancedAnalyticsProps) {
  const { t, formatNumber } = useI18n();
  const [exportFormat, setExportFormat] = useState<'csv' | 'json'>('csv');

  // Fetch data with React Query
  const { data: sessionData, isLoading: sessionLoading, error: sessionError } = useSessionDetailQuery(sessionId);
  const { data: statsData, isLoading: statsLoading, error: statsError } = useSessionStatisticsQuery(sessionId);
  const { data: comparisonStatsData } = useSessionStatisticsQuery(comparisonSessionId || null);

  const loading = sessionLoading || statsLoading;
  const error = sessionError?.message || statsError?.message || null;

  // Compute analytics with memoization
  const analytics = useMemo(() => {
    if (!sessionData || !statsData) return null;
    return computeAdvancedAnalytics(sessionData.session, statsData.statistics);
  }, [sessionData, statsData]);

  // Compute comparison with memoization
  const comparison = useMemo(() => {
    if (!comparisonSessionId || !statsData || !comparisonStatsData) return null;
    return compareSessions(
      statsData.statistics,
      sessionId || '',
      comparisonStatsData.statistics,
      comparisonSessionId
    );
  }, [sessionId, comparisonSessionId, statsData, comparisonStatsData]);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  const handleExport = () => {
    if (!analytics || !sessionId || !statsData) return;

    try {
      const config: ExportConfig = {
        format: exportFormat,
        includeRawData: true,
        includeCharts: false,
        sections: {
          statistics: true,
          analytics: true,
          toolUsage: true,
          subagents: true,
          recommendations: true,
        },
      };

      const files = exportData(config, sessionId, statsData.statistics, analytics);
      downloadFiles(files, exportFormat);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Failed to export data');
    }
  };

  // Prepare data for token usage heatmap
  const heatmapData = (analytics?.tokenUsageHeatmap.dataPoints ?? []).map((dp) => ({
    time: new Date(dp.timestamp).toLocaleTimeString(),
    tokens: dp.tokens,
    input: dp.inputTokens,
    output: dp.outputTokens,
    cache: dp.cacheReadTokens + dp.cacheCreationTokens,
  }));

  // Prepare data for expensive operations chart
  const expensiveOpsData = (analytics?.expensiveOperations ?? []).slice(0, 10).map((op) => ({
    name: op.name.substring(0, 30) + (op.name.length > 30 ? '...' : ''),
    tokens: op.tokens,
    type: op.type,
  }));

  // Prepare data for subagent efficiency
  const subagentEffData = (analytics?.subagentEfficiency ?? []).map((eff) => ({
    agent: eff.agentType,
    score: eff.efficiencyScore,
    invocations: eff.totalInvocations,
  }));

  // Compute time-based bottleneck if time_breakdown is available
  const allBottlenecks = [...(analytics?.performanceBottlenecks ?? [])];
  const tb = statsData?.statistics?.time_breakdown;
  if (tb) {
    const categories = [
      { name: 'Model', percent: tb.model_time_percent },
      { name: 'Tool execution', percent: tb.tool_time_percent },
      { name: 'User', percent: tb.user_time_percent },
    ];
    const highest = categories.reduce((a, b) => (a.percent > b.percent ? a : b));
    if (highest.percent > 60) {
      allBottlenecks.unshift({
        type: 'long_duration' as const,
        severity: highest.percent > 80 ? 'high' as const : 'medium' as const,
        description: `${highest.name} dominates session time (${highest.percent.toFixed(1)}%)`,
        affectedComponent: 'Session time distribution',
        impactMetrics: {},
        recommendation: `Investigate why ${highest.name.toLowerCase()} time is disproportionately high`,
        relatedMessages: [],
      });
    }
  }

  const formatTokenWithFull = (num: number): string =>
    formatTokenWithRawValue(num, formatNumber);

  return (
    <div className="advanced-analytics">
      <div className="analytics-header">
        <h2 className="analytics-title">{t('advanced.title')}</h2>
        <div className="export-controls">
          <select
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as 'csv' | 'json')}
            className="export-format-select"
          >
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <button
            onClick={handleExport}
            className="export-button"
            disabled={!sessionId || !analytics || loading || !!error}
            title={!sessionId ? 'Select a session to export detail analytics' : undefined}
          >
            Export Data
          </button>
        </div>
      </div>

      <CrossSessionOverview />

      {!sessionId && (
        <div className="session-insights-state session-insights-state--empty">
          <p>{t('advanced.emptyPrimary')}</p>
          <p>{t('advanced.emptySecondary')}</p>
        </div>
      )}

      {sessionId && loading && (
        <div className="session-insights-state session-insights-state--loading">
          <div className="loading-spinner">Computing session deep-dive analytics...</div>
        </div>
      )}

      {sessionId && !loading && error && (
        <div className="session-insights-state session-insights-state--error">
          <p className="error-text">{error}</p>
        </div>
      )}

      {sessionId && !loading && !error && analytics && (
        <>
          {/* Visual Metrics Comparison */}
          {comparisonSessionId && comparisonStatsData && (
            <MetricComparison
              sessionAId={sessionId}
              sessionBId={comparisonSessionId}
              statisticsA={statsData?.statistics || null}
              statisticsB={comparisonStatsData.statistics}
            />
          )}

          {/* Session Comparison */}
          {comparison && (
            <div className="comparison-section">
              <h3 className="section-title">Session Comparison</h3>
              <div className="comparison-grid">
                <div className="comparison-card">
                  <h4>Token Difference</h4>
                  <div
                    className={`comparison-value ${comparison.differences.totalTokensDiff > 0 ? 'positive' : 'negative'}`}
                    title={formatNumber(comparison.differences.totalTokensDiff)}
                  >
                    {comparison.differences.totalTokensDiff > 0 ? '+' : ''}
                    {formatTokenCount(comparison.differences.totalTokensDiff)}
                    {' '}
                    ({comparison.differences.totalTokensDiffPercent.toFixed(1)}%)
                  </div>
                </div>
                <div className="comparison-card">
                  <h4>Message Difference</h4>
                  <div className={`comparison-value ${comparison.differences.messageDiff > 0 ? 'positive' : 'negative'}`}>
                    {comparison.differences.messageDiff > 0 ? '+' : ''}
                    {comparison.differences.messageDiff}
                  </div>
                </div>
                <div className="comparison-card">
                  <h4>Duration Difference</h4>
                  <div className="comparison-value">
                    {comparison.differences.durationDiff > 0 ? '+' : ''}
                    {comparison.differences.durationDiff.toFixed(0)}s
                  </div>
                </div>
              </div>
              <div className="comparison-insights">
                <h4>Insights</h4>
                <ul>
                  {comparison.insights.map((insight, idx) => (
                    <li key={idx}>{insight}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          {/* Token Usage Heatmap */}
          <div className="chart-section">
            <h3 className="section-title">Token Usage Over Time</h3>
            <div className="heatmap-summary">
              <span title={formatNumber(analytics.tokenUsageHeatmap.totalTokens)}>
                Total: {formatTokenCount(analytics.tokenUsageHeatmap.totalTokens)}
              </span>
              <span title={formatNumber(analytics.tokenUsageHeatmap.peakUsage.tokens)}>
                Peak: {formatTokenCount(analytics.tokenUsageHeatmap.peakUsage.tokens)} at {new Date(analytics.tokenUsageHeatmap.peakUsage.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={heatmapData}>
                <CartesianGrid {...CHART_GRID_PROPS} />
                <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} {...CHART_AXIS_PROPS} />
                <YAxis tickFormatter={formatTokenAxisTick} {...CHART_AXIS_PROPS} />
                <Tooltip
                  formatter={(value) => formatTokenWithFull(Number(value))}
                  contentStyle={CHART_TOOLTIP_STYLE}
                />
                <Legend {...CHART_LEGEND_PROPS} />
                <Area type="monotone" dataKey="input" stackId="1" stroke={CHART_COLORS.input} fill={CHART_COLORS.input} name="Input" />
                <Area type="monotone" dataKey="output" stackId="1" stroke={CHART_COLORS.output} fill={CHART_COLORS.output} name="Output" />
                <Area type="monotone" dataKey="cache" stackId="1" stroke={CHART_COLORS.cache} fill={CHART_COLORS.cache} name="Cache" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Expensive Operations */}
          {analytics.expensiveOperations.length > 0 && (
            <div className="chart-section">
              <h3 className="section-title">Top 10 Most Expensive Operations</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={expensiveOpsData} layout="horizontal">
                  <CartesianGrid {...CHART_GRID_PROPS} />
                  <XAxis dataKey="name" angle={-45} textAnchor="end" height={100} {...CHART_AXIS_PROPS} />
                  <YAxis tickFormatter={formatTokenAxisTick} {...CHART_AXIS_PROPS} />
                  <Tooltip
                    formatter={(value) => formatTokenWithFull(Number(value))}
                    contentStyle={CHART_TOOLTIP_STYLE}
                  />
                  <Legend {...CHART_LEGEND_PROPS} />
                  <Bar dataKey="tokens" fill={CHART_COLORS.danger} name="Tokens" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Tool Usage Patterns */}
          {analytics.toolUsagePatterns.length > 0 && (
            <div className="patterns-section">
              <h3 className="section-title">Tool Usage Patterns</h3>
              <div className="table-container">
                <table className="patterns-table">
                  <thead>
                    <tr>
                      <th>Tool</th>
                      <th>Calls</th>
                      <th>Avg Tokens/Call</th>
                      <th>Avg Latency</th>
                      <th>Success Rate</th>
                      <th>Common Parameters</th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.toolUsagePatterns.slice(0, 10).map((pattern) => {
                      const toolStat = statsData?.statistics?.tool_calls?.find(
                        (tc) => tc.tool_name === pattern.toolName
                      );
                      const avgLatency = toolStat?.avg_latency_seconds || 0;
                      return (
                        <tr key={pattern.toolName}>
                          <td className="tool-name">{pattern.toolName}</td>
                          <td>{formatNumber(pattern.totalCalls)}</td>
                          <td title={formatNumber(Math.round(pattern.averageTokensPerCall))}>
                            {formatTokenCount(Math.round(pattern.averageTokensPerCall))}
                          </td>
                          <td>{avgLatency > 0 ? avgLatency.toFixed(2) + 's' : '--'}</td>
                          <td className={pattern.successRate < 0.7 ? 'low-success' : ''}>
                            {(pattern.successRate * 100).toFixed(1)}%
                          </td>
                          <td className="params-cell">
                            {Object.keys(pattern.commonParameters).slice(0, 3).join(', ')}
                            {Object.keys(pattern.commonParameters).length > 3 ? '...' : ''}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Subagent Efficiency */}
          {analytics.subagentEfficiency.length > 0 && (
            <div className="chart-section">
              <h3 className="section-title">Subagent Efficiency Metrics</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={subagentEffData}>
                  <CartesianGrid {...CHART_GRID_PROPS} />
                  <XAxis dataKey="agent" {...CHART_AXIS_PROPS} />
                  <YAxis yAxisId="left" {...CHART_AXIS_PROPS} />
                  <YAxis yAxisId="right" orientation="right" {...CHART_AXIS_PROPS} />
                  <Tooltip contentStyle={CHART_TOOLTIP_STYLE} />
                  <Legend {...CHART_LEGEND_PROPS} />
                  <Bar yAxisId="left" dataKey="score" fill={CHART_COLORS.compareA} name="Efficiency Score" />
                  <Bar yAxisId="right" dataKey="invocations" fill={CHART_COLORS.compareB} name="Invocations" />
                </BarChart>
              </ResponsiveContainer>
              <div className="efficiency-details">
                {analytics.subagentEfficiency.map((eff) => (
                  <div key={eff.agentType} className="efficiency-card">
                    <h4>{eff.agentType}</h4>
                    <div className="efficiency-stats">
                      <span>Avg Messages: {eff.averageMessages.toFixed(1)}</span>
                      <span title={formatNumber(Math.round(eff.averageTokens))}>
                        Avg Tokens: {formatTokenCount(Math.round(eff.averageTokens))}
                      </span>
                      <span>Avg Duration: {eff.averageDuration.toFixed(1)}s</span>
                      <span title={formatNumber(Math.round(eff.tokensPerMinute))}>
                        Tokens/min: {formatTokenCount(Math.round(eff.tokensPerMinute))}
                      </span>
                    </div>
                    {eff.recommendations.length > 0 && (
                      <div className="efficiency-recommendations">
                        <strong>Recommendations:</strong>
                        <ul>
                          {eff.recommendations.map((rec, idx) => (
                            <li key={idx}>{rec}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Performance Bottlenecks */}
          {allBottlenecks.length > 0 && (
            <div className="bottlenecks-section">
              <h3 className="section-title">Performance Bottlenecks</h3>
              <div className="bottlenecks-list">
                {allBottlenecks.map((bottleneck, idx) => (
                  <div key={idx} className={`bottleneck-card severity-${bottleneck.severity}`}>
                    <div className="bottleneck-header">
                      <span className={`severity-badge ${bottleneck.severity}`}>{bottleneck.severity}</span>
                      <span className="bottleneck-type">{bottleneck.type.replace('_', ' ')}</span>
                    </div>
                    <h4>{bottleneck.description}</h4>
                    <p className="bottleneck-component">Affects: {bottleneck.affectedComponent}</p>
                    <div className="bottleneck-impact">
                      {bottleneck.impactMetrics.tokensWasted && (
                        <span title={formatNumber(bottleneck.impactMetrics.tokensWasted)}>
                          Tokens: {formatTokenCount(bottleneck.impactMetrics.tokensWasted)}
                        </span>
                      )}
                      {bottleneck.impactMetrics.errorCount && (
                        <span>Errors: {bottleneck.impactMetrics.errorCount}</span>
                      )}
                    </div>
                    <p className="bottleneck-recommendation">
                      <strong>Recommendation:</strong> {bottleneck.recommendation}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Recommendations */}
          {analytics.recommendations.length > 0 && (
            <div className="recommendations-section">
              <h3 className="section-title">Usage Recommendations</h3>
              <div className="recommendations-list">
                {analytics.recommendations.map((rec, idx) => (
                  <div key={idx} className={`recommendation-card priority-${rec.priority}`}>
                    <div className="recommendation-header">
                      <span className={`priority-badge ${rec.priority}`}>{rec.priority} priority</span>
                      <span className="recommendation-category">{rec.category}</span>
                    </div>
                    <h4>{rec.title}</h4>
                    <p>{rec.description}</p>
                    {rec.potentialSavings && (
                      <div className="potential-savings">
                        <strong>Potential Savings:</strong>
                        {rec.potentialSavings.tokens && (
                          <span title={formatNumber(rec.potentialSavings.tokens)}>
                            {' '}
                            {formatTokenCount(rec.potentialSavings.tokens)}
                            {' '}
                            tokens
                          </span>
                        )}
                        {rec.potentialSavings.time && (
                          <span> {rec.potentialSavings.time}s time</span>
                        )}
                      </div>
                    )}
                    <div className="action-items">
                      <strong>Action Items:</strong>
                      <ul>
                        {rec.actionItems.map((action, actionIdx) => (
                          <li key={actionIdx}>{action}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

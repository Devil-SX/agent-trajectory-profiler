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

import { useEffect, useState, useCallback } from 'react';
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
import { fetchSessionDetail, fetchSessionStatistics, APIError } from '../api/sessions';
import type { AdvancedAnalytics as AdvancedAnalyticsType, SessionComparison } from '../types/analytics';
import {
  computeAdvancedAnalytics,
  compareSessions,
} from '../utils/analyticsComputer';
import {
  exportData,
  downloadFiles,
} from '../utils/exportData';
import type { ExportConfig } from '../types/analytics';
import './AdvancedAnalytics.css';

interface AdvancedAnalyticsProps {
  sessionId: string | null;
  comparisonSessionId?: string | null;
}

export function AdvancedAnalytics({ sessionId, comparisonSessionId }: AdvancedAnalyticsProps) {
  const [analytics, setAnalytics] = useState<AdvancedAnalyticsType | null>(null);
  const [comparison, setComparison] = useState<SessionComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportFormat, setExportFormat] = useState<'csv' | 'json'>('csv');

  const loadAnalytics = useCallback(async (id: string) => {
    try {
      setLoading(true);
      setError(null);

      const [sessionData, statsData] = await Promise.all([
        fetchSessionDetail(id),
        fetchSessionStatistics(id),
      ]);

      const computed = computeAdvancedAnalytics(sessionData.session, statsData.statistics);
      setAnalytics(computed);
    } catch (err) {
      const errorMessage = err instanceof APIError ? err.message : 'Failed to load analytics';
      setError(errorMessage);
      toast.error(errorMessage);
      console.error('Failed to load analytics:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadComparison = useCallback(async (id1: string, id2: string) => {
    try {
      const [stats1, stats2] = await Promise.all([
        fetchSessionStatistics(id1),
        fetchSessionStatistics(id2),
      ]);

      const comp = compareSessions(stats1.statistics, id1, stats2.statistics, id2);
      setComparison(comp);
    } catch (err) {
      const errorMessage = err instanceof APIError ? err.message : 'Failed to load session comparison';
      toast.error(errorMessage);
      console.error('Failed to load comparison:', err);
      setComparison(null);
    }
  }, []);

  useEffect(() => {
    if (!sessionId) {
      setAnalytics(null);
      setComparison(null);
      return;
    }

    loadAnalytics(sessionId);

    if (comparisonSessionId && comparisonSessionId !== sessionId) {
      loadComparison(sessionId, comparisonSessionId);
    } else {
      setComparison(null);
    }
  }, [sessionId, comparisonSessionId, loadAnalytics, loadComparison]);

  const handleExport = async () => {
    if (!analytics || !sessionId) return;

    try {
      const statsResponse = await fetchSessionStatistics(sessionId);

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

      const files = exportData(config, sessionId, statsResponse.statistics, analytics);
      downloadFiles(files, exportFormat);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Failed to export data');
    }
  };

  if (!sessionId) {
    return (
      <div className="advanced-analytics empty">
        <p>Select a session to view advanced analytics</p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="advanced-analytics loading">
        <div className="loading-spinner">Computing advanced analytics...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="advanced-analytics error">
        <p className="error-text">{error}</p>
      </div>
    );
  }

  if (!analytics) {
    return null;
  }

  // Prepare data for token usage heatmap
  const heatmapData = analytics.tokenUsageHeatmap.dataPoints.map((dp) => ({
    time: new Date(dp.timestamp).toLocaleTimeString(),
    tokens: dp.tokens,
    input: dp.inputTokens,
    output: dp.outputTokens,
    cache: dp.cacheReadTokens + dp.cacheCreationTokens,
  }));

  // Prepare data for expensive operations chart
  const expensiveOpsData = analytics.expensiveOperations.slice(0, 10).map((op) => ({
    name: op.name.substring(0, 30) + (op.name.length > 30 ? '...' : ''),
    tokens: op.tokens,
    type: op.type,
  }));

  // Prepare data for subagent efficiency
  const subagentEffData = analytics.subagentEfficiency.map((eff) => ({
    agent: eff.agentType,
    score: eff.efficiencyScore,
    invocations: eff.totalInvocations,
  }));

  const formatNumber = (num: number): string => num.toLocaleString();

  return (
    <div className="advanced-analytics">
      <div className="analytics-header">
        <h2 className="analytics-title">Advanced Analytics</h2>
        <div className="export-controls">
          <select
            value={exportFormat}
            onChange={(e) => setExportFormat(e.target.value as 'csv' | 'json')}
            className="export-format-select"
          >
            <option value="csv">CSV</option>
            <option value="json">JSON</option>
          </select>
          <button onClick={handleExport} className="export-button">
            Export Data
          </button>
        </div>
      </div>

      {/* Session Comparison */}
      {comparison && (
        <div className="comparison-section">
          <h3 className="section-title">Session Comparison</h3>
          <div className="comparison-grid">
            <div className="comparison-card">
              <h4>Token Difference</h4>
              <div className={`comparison-value ${comparison.differences.totalTokensDiff > 0 ? 'positive' : 'negative'}`}>
                {comparison.differences.totalTokensDiff > 0 ? '+' : ''}
                {formatNumber(comparison.differences.totalTokensDiff)} ({comparison.differences.totalTokensDiffPercent.toFixed(1)}%)
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
          <span>Total: {formatNumber(analytics.tokenUsageHeatmap.totalTokens)}</span>
          <span>Peak: {formatNumber(analytics.tokenUsageHeatmap.peakUsage.tokens)} at {new Date(analytics.tokenUsageHeatmap.peakUsage.timestamp).toLocaleTimeString()}</span>
        </div>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={heatmapData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="time" angle={-45} textAnchor="end" height={80} />
            <YAxis />
            <Tooltip formatter={(value) => formatNumber(value as number)} />
            <Legend />
            <Area type="monotone" dataKey="input" stackId="1" stroke="#1976d2" fill="#1976d2" name="Input" />
            <Area type="monotone" dataKey="output" stackId="1" stroke="#388e3c" fill="#388e3c" name="Output" />
            <Area type="monotone" dataKey="cache" stackId="1" stroke="#f57c00" fill="#f57c00" name="Cache" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Expensive Operations */}
      {analytics.expensiveOperations.length > 0 && (
        <div className="chart-section">
          <h3 className="section-title">Top 10 Most Expensive Operations</h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={expensiveOpsData} layout="horizontal">
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="name" angle={-45} textAnchor="end" height={100} />
              <YAxis />
              <Tooltip formatter={(value) => formatNumber(value as number)} />
              <Legend />
              <Bar dataKey="tokens" fill="#d32f2f" name="Tokens" />
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
                  <th>Success Rate</th>
                  <th>Common Parameters</th>
                </tr>
              </thead>
              <tbody>
                {analytics.toolUsagePatterns.slice(0, 10).map((pattern) => (
                  <tr key={pattern.toolName}>
                    <td className="tool-name">{pattern.toolName}</td>
                    <td>{formatNumber(pattern.totalCalls)}</td>
                    <td>{Math.round(pattern.averageTokensPerCall)}</td>
                    <td className={pattern.successRate < 0.7 ? 'low-success' : ''}>
                      {(pattern.successRate * 100).toFixed(1)}%
                    </td>
                    <td className="params-cell">
                      {Object.keys(pattern.commonParameters).slice(0, 3).join(', ')}
                      {Object.keys(pattern.commonParameters).length > 3 ? '...' : ''}
                    </td>
                  </tr>
                ))}
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
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="agent" />
              <YAxis yAxisId="left" />
              <YAxis yAxisId="right" orientation="right" />
              <Tooltip />
              <Legend />
              <Bar yAxisId="left" dataKey="score" fill="#7b1fa2" name="Efficiency Score" />
              <Bar yAxisId="right" dataKey="invocations" fill="#0097a7" name="Invocations" />
            </BarChart>
          </ResponsiveContainer>
          <div className="efficiency-details">
            {analytics.subagentEfficiency.map((eff) => (
              <div key={eff.agentType} className="efficiency-card">
                <h4>{eff.agentType}</h4>
                <div className="efficiency-stats">
                  <span>Avg Messages: {eff.averageMessages.toFixed(1)}</span>
                  <span>Avg Tokens: {formatNumber(Math.round(eff.averageTokens))}</span>
                  <span>Avg Duration: {eff.averageDuration.toFixed(1)}s</span>
                  <span>Tokens/min: {formatNumber(Math.round(eff.tokensPerMinute))}</span>
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
      {analytics.performanceBottlenecks.length > 0 && (
        <div className="bottlenecks-section">
          <h3 className="section-title">Performance Bottlenecks</h3>
          <div className="bottlenecks-list">
            {analytics.performanceBottlenecks.map((bottleneck, idx) => (
              <div key={idx} className={`bottleneck-card severity-${bottleneck.severity}`}>
                <div className="bottleneck-header">
                  <span className={`severity-badge ${bottleneck.severity}`}>{bottleneck.severity}</span>
                  <span className="bottleneck-type">{bottleneck.type.replace('_', ' ')}</span>
                </div>
                <h4>{bottleneck.description}</h4>
                <p className="bottleneck-component">Affects: {bottleneck.affectedComponent}</p>
                <div className="bottleneck-impact">
                  {bottleneck.impactMetrics.tokensWasted && (
                    <span>Tokens: {formatNumber(bottleneck.impactMetrics.tokensWasted)}</span>
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
                      <span> {formatNumber(rec.potentialSavings.tokens)} tokens</span>
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
    </div>
  );
}

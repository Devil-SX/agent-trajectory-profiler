/**
 * BottleneckInsight component displays bottleneck analysis with:
 * - Color-coded badge (Model/Tool/User)
 * - Percentage indicator
 * - Optimization suggestion
 */

import type { TimeBreakdown } from '../types/session';
import { MetricTerm } from './MetricHelp';
import './BottleneckInsight.css';

interface BottleneckInsightProps {
  timeBreakdown: TimeBreakdown | null | undefined;
}

const BOTTLENECK_CONFIG = {
  Model: {
    color: '#ef4444',
    icon: '🔴',
    label: 'Model (Inference)',
    suggestion: 'Inference is the dominant cost. Consider prompt optimization or using a smaller model.',
  },
  Tool: {
    color: '#f97316',
    icon: '🟠',
    label: 'Tool (Execution)',
    suggestion: 'Tool execution dominates. Look for slow file reads, network calls, or heavy bash commands.',
  },
  User: {
    color: '#22c55e',
    icon: '🟢',
    label: 'User (Response)',
    suggestion: 'Human response time dominates. The agent is waiting on you.',
  },
};

export function BottleneckInsight({ timeBreakdown }: BottleneckInsightProps) {
  if (!timeBreakdown || !timeBreakdown.user_interaction_count) {
    return null;
  }

  const bottleneckType = timeBreakdown.user_interaction_count > 0 
    ? (timeBreakdown.model_time_percent > timeBreakdown.tool_time_percent && 
       timeBreakdown.model_time_percent > timeBreakdown.user_time_percent 
       ? 'Model' 
       : timeBreakdown.tool_time_percent > timeBreakdown.user_time_percent 
       ? 'Tool' 
       : 'User')
    : 'Model';

  const config = BOTTLENECK_CONFIG[bottleneckType as keyof typeof BOTTLENECK_CONFIG];

  const percentage = 
    bottleneckType === 'Model'
      ? timeBreakdown.model_time_percent
      : bottleneckType === 'Tool'
      ? timeBreakdown.tool_time_percent
      : timeBreakdown.user_time_percent;

  return (
    <div className="bottleneck-insight">
      <div className="bottleneck-header">
        <div className="bottleneck-badge" style={{ borderColor: config.color }}>
          <span className="bottleneck-icon">{config.icon}</span>
          <span className="bottleneck-label">{config.label}</span>
          <span className="bottleneck-percentage" style={{ color: config.color }}>
            {percentage.toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="bottleneck-content">
        <p className="bottleneck-title">
          <MetricTerm metricId="bottleneck">Bottleneck Analysis</MetricTerm>
        </p>
        <p className="bottleneck-suggestion">{config.suggestion}</p>

        <div className="bottleneck-metrics">
          <div className="metric">
            <span className="metric-label">Interactions/hour:</span>
            <span className="metric-value">{timeBreakdown.interactions_per_hour.toFixed(1)}</span>
          </div>
          {timeBreakdown.model_timeout_count > 0 && (
            <div className="metric warning">
              <span className="metric-label">Model timeouts:</span>
              <span className="metric-value">{timeBreakdown.model_timeout_count}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

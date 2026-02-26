/**
 * BashCommandTable component displays bash command statistics.
 *
 * Features:
 * - Sortable table by count/latency
 * - Highlights slow commands (>5s avg)
 * - Shows command name, count, total time, avg time, output size
 */

import { useState } from 'react';
import type { BashBreakdown, BashCommandStats } from '../types/session';
import './BashCommandTable.css';

interface BashCommandTableProps {
  bashBreakdown: BashBreakdown | null | undefined;
}

type SortKey = 'command_name' | 'count' | 'total_latency_seconds' | 'avg_latency_seconds';
type SortOrder = 'asc' | 'desc';

const formatTime = (seconds: number): string => {
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
  if (seconds < 60) return `${seconds.toFixed(2)}s`;
  const minutes = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${minutes}m ${secs}s`;
};

const formatSize = (chars: number): string => {
  if (chars === 0) return '--';
  if (chars < 1024) return `${chars}B`;
  if (chars < 1024 * 1024) return `${(chars / 1024).toFixed(1)}K`;
  return `${(chars / (1024 * 1024)).toFixed(1)}M`;
};

export function BashCommandTable({ bashBreakdown }: BashCommandTableProps) {
  const [sortKey, setSortKey] = useState<SortKey>('count');
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc');

  if (!bashBreakdown || bashBreakdown.command_stats.length === 0) {
    return (
      <div className="bash-command-table empty">
        <p>No bash commands executed</p>
      </div>
    );
  }

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortOrder('desc');
    }
  };

  const sortedCommands = [...bashBreakdown.command_stats].sort((a, b) => {
    const aVal = a[sortKey];
    const bVal = b[sortKey];
    const multiplier = sortOrder === 'asc' ? 1 : -1;

    if (typeof aVal === 'string' && typeof bVal === 'string') {
      return multiplier * aVal.localeCompare(bVal);
    }
    return multiplier * ((aVal as number) - (bVal as number));
  });

  const getSortIcon = (key: SortKey) => {
    if (sortKey !== key) return '⬍';
    return sortOrder === 'asc' ? '▲' : '▼';
  };

  const isSlowCommand = (cmd: BashCommandStats) => cmd.avg_latency_seconds > 5;

  return (
    <div className="bash-command-table">
      <div className="table-header">
        <h3>Bash Command Analysis</h3>
        <div className="table-summary">
          {bashBreakdown.total_calls} calls • {bashBreakdown.total_sub_commands} sub-commands • 
          avg {bashBreakdown.avg_commands_per_call.toFixed(1)} commands/call
        </div>
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th onClick={() => handleSort('command_name')} className="sortable">
                Command {getSortIcon('command_name')}
              </th>
              <th onClick={() => handleSort('count')} className="sortable right">
                Count {getSortIcon('count')}
              </th>
              <th onClick={() => handleSort('total_latency_seconds')} className="sortable right">
                Total Time {getSortIcon('total_latency_seconds')}
              </th>
              <th onClick={() => handleSort('avg_latency_seconds')} className="sortable right">
                Avg Time {getSortIcon('avg_latency_seconds')}
              </th>
              <th className="right">Output</th>
            </tr>
          </thead>
          <tbody>
            {sortedCommands.map((cmd, index) => (
              <tr key={index} className={isSlowCommand(cmd) ? 'slow-command' : ''}>
                <td className="command-name">
                  <code>{cmd.command_name}</code>
                  {isSlowCommand(cmd) && <span className="slow-badge">🐢 slow</span>}
                </td>
                <td className="right">{cmd.count}</td>
                <td className="right">{formatTime(cmd.total_latency_seconds)}</td>
                <td className="right">{formatTime(cmd.avg_latency_seconds)}</td>
                <td className="right">{formatSize(cmd.total_output_chars)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

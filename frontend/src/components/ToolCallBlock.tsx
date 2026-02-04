/**
 * ToolCallBlock component for displaying tool calls with expandable parameters.
 *
 * Features:
 * - Tool category badges with icons
 * - Color coding by tool category
 * - Expandable/collapsible parameter section
 * - Result display with error states
 * - Token cost display when available
 */

import { useState } from 'react';
import type { ToolUseContent, ToolResultContent } from '../types/session';
import { categorizeToolCall, getCategoryIcon, getCategoryName } from '../utils/toolCategories';
import './ToolCallBlock.css';

interface ToolCallBlockProps {
  toolUse: ToolUseContent;
  toolResult?: ToolResultContent;
  tokens?: {
    input: number;
    output: number;
    total: number;
  };
}

// Format JSON for display
function formatJSON(obj: unknown): string {
  try {
    return JSON.stringify(obj, null, 2);
  } catch {
    return String(obj);
  }
}

// Format result content for display
function formatResultContent(content: string | Array<Record<string, unknown>>): string {
  if (typeof content === 'string') {
    return content;
  }
  return formatJSON(content);
}

export function ToolCallBlock({ toolUse, toolResult, tokens }: ToolCallBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [showResult, setShowResult] = useState(false);

  const category = categorizeToolCall(toolUse.name);
  const icon = getCategoryIcon(category);
  const categoryName = getCategoryName(category);
  const hasError = toolResult?.is_error === true;
  const hasResult = toolResult !== undefined;

  const toggleExpanded = () => setIsExpanded(!isExpanded);
  const toggleResult = () => setShowResult(!showResult);

  // Check if there are any parameters to display
  const hasParameters = Object.keys(toolUse.input).length > 0;

  return (
    <div className={`tool-call-block category-${category} ${hasError ? 'has-error' : ''}`}>
      <div className="tool-call-header">
        <div className="tool-call-info">
          <span className="tool-icon">{icon}</span>
          <span className="tool-name">{toolUse.name}</span>
          <span className="tool-category-badge">{categoryName}</span>
          {hasError && <span className="tool-error-badge">Error</span>}
        </div>
        <div className="tool-call-actions">
          {tokens && (
            <span className="tool-tokens" title={`Input: ${tokens.input} | Output: ${tokens.output}`}>
              {tokens.total.toLocaleString()} tokens
            </span>
          )}
          {hasParameters && (
            <button
              className="expand-button"
              onClick={toggleExpanded}
              aria-label={isExpanded ? 'Hide parameters' : 'Show parameters'}
            >
              {isExpanded ? '▼' : '▶'}
            </button>
          )}
        </div>
      </div>

      {isExpanded && hasParameters && (
        <div className="tool-call-parameters">
          <div className="parameters-header">Parameters:</div>
          <pre className="parameters-content">{formatJSON(toolUse.input)}</pre>
        </div>
      )}

      {hasResult && (
        <div className="tool-result-section">
          <button
            className="result-toggle-button"
            onClick={toggleResult}
            aria-label={showResult ? 'Hide result' : 'Show result'}
          >
            <span className="result-status-icon">
              {hasError ? '❌' : '✅'}
            </span>
            <span className="result-label">
              {hasError ? 'Error Result' : 'Result'}
            </span>
            <span className="result-toggle-icon">{showResult ? '▼' : '▶'}</span>
          </button>

          {showResult && (
            <div className={`tool-result-content ${hasError ? 'error' : 'success'}`}>
              <pre>{formatResultContent(toolResult.content)}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

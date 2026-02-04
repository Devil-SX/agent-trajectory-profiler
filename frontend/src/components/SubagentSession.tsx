/**
 * SubagentSession component for displaying nested subagent conversations.
 *
 * Features:
 * - Expandable/collapsible subagent sections
 * - Visual nesting with distinct colors and borders
 * - Subagent type label with icon
 * - Recursive component for deep nesting support
 * - Smooth transitions for expand/collapse
 */

import React, { useState } from 'react';
import type { MessageRecord, SubagentType } from '../types/session';
import './SubagentSession.css';

interface SubagentSessionProps {
  agentId: string;
  agentType: SubagentType;
  messages: MessageRecord[];
  nestLevel?: number;
  renderMessageContent: (message: MessageRecord) => React.ReactElement | React.ReactElement[];
  formatTimestamp: (timestamp: string) => string;
}

const AGENT_TYPE_ICONS: Record<SubagentType, string> = {
  Explore: '🔍',
  Bash: '💻',
  'general-purpose': '🤖',
  Plan: '📋',
  'test-runner': '🧪',
  'build-validator': '🔨',
  'statusline-setup': '⚙️',
  prompt_suggestion: '💡',
  other: '🔧',
};

const MAX_NEST_LEVEL = 5;

export function SubagentSession({
  agentId,
  agentType,
  messages,
  nestLevel = 0,
  renderMessageContent,
  formatTimestamp,
}: SubagentSessionProps) {
  const [isExpanded, setIsExpanded] = useState(true);

  // Cap nesting level to prevent excessive depth
  const effectiveNestLevel = Math.min(nestLevel, MAX_NEST_LEVEL);

  // Group messages by nested subagent
  const nestedSubagents = new Map<string, MessageRecord[]>();
  const mainMessages: MessageRecord[] = [];

  messages.forEach((msg) => {
    // Check if this message belongs to a further nested subagent
    if (msg.agentId && msg.agentId !== agentId) {
      const nestedAgentId = msg.agentId;
      if (!nestedSubagents.has(nestedAgentId)) {
        nestedSubagents.set(nestedAgentId, []);
      }
      nestedSubagents.get(nestedAgentId)!.push(msg);
    } else {
      mainMessages.push(msg);
    }
  });

  const toggleExpand = () => {
    setIsExpanded(!isExpanded);
  };

  const icon = AGENT_TYPE_ICONS[agentType] || AGENT_TYPE_ICONS.other;

  return (
    <div className={`subagent-session nest-level-${effectiveNestLevel}`}>
      <div className="subagent-header" onClick={toggleExpand}>
        <div className="subagent-header-content">
          <span className="subagent-icon">{icon}</span>
          <span className="subagent-type">{agentType}</span>
          <span className="subagent-id" title={agentId}>
            {agentId.substring(0, 7)}
          </span>
          <span className="message-count-badge">{messages.length}</span>
        </div>
        <button
          className={`expand-toggle ${isExpanded ? 'expanded' : 'collapsed'}`}
          aria-label={isExpanded ? 'Collapse' : 'Expand'}
        >
          {isExpanded ? '▼' : '▶'}
        </button>
      </div>

      {isExpanded && (
        <div className="subagent-content">
          {mainMessages.map((message) => (
            <div key={message.uuid} className="subagent-message">
              <div className="message-header">
                <span className="message-role">{message.message?.role || 'unknown'}</span>
                <span className="message-timestamp">{formatTimestamp(message.timestamp)}</span>
              </div>
              <div className="message-content">{renderMessageContent(message)}</div>
            </div>
          ))}

          {/* Recursively render nested subagents */}
          {Array.from(nestedSubagents.entries()).map(([nestedAgentId, nestedMessages]) => {
            // Default to 'other' for nested subagents
            const nestedAgentType = 'other' as SubagentType;
            return (
              <SubagentSession
                key={nestedAgentId}
                agentId={nestedAgentId}
                agentType={nestedAgentType}
                messages={nestedMessages}
                nestLevel={effectiveNestLevel + 1}
                renderMessageContent={renderMessageContent}
                formatTimestamp={formatTimestamp}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}

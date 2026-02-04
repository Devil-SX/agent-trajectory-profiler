/**
 * Utility functions for categorizing and displaying tool calls.
 */

import type { ToolCategory } from '../types/session';

// Categorize tools for better visualization
export function categorizeToolCall(toolName: string): ToolCategory {
  const name = toolName.toLowerCase();

  // File read operations
  if (name === 'read' || name === 'readmcpresourcetool' || name === 'listmcpresourcestool') {
    return 'file-read';
  }

  // File write operations
  if (name === 'write' || name === 'edit' || name === 'notebookedit') {
    return 'file-write';
  }

  // File search operations
  if (name === 'glob' || name === 'grep') {
    return 'file-search';
  }

  // Execution
  if (name === 'bash' || name === 'taskoutput') {
    return 'execution';
  }

  // Agent/Task management
  if (name === 'task' || name === 'taskstop' || name === 'enterplanmode' || name === 'exitplanmode') {
    return 'agent';
  }

  // Web operations
  if (name === 'webfetch' || name === 'websearch') {
    return 'web';
  }

  // Analysis
  if (name === 'skill' || name === 'askuserquestion' || name === 'todowrite') {
    return 'analysis';
  }

  return 'other';
}

// Get icon for tool category
export function getCategoryIcon(category: ToolCategory): string {
  switch (category) {
    case 'file-read':
      return '📖';
    case 'file-write':
      return '✏️';
    case 'file-search':
      return '🔍';
    case 'execution':
      return '⚙️';
    case 'agent':
      return '🤖';
    case 'web':
      return '🌐';
    case 'analysis':
      return '📊';
    case 'other':
      return '🔧';
  }
}

// Get display name for category
export function getCategoryName(category: ToolCategory): string {
  switch (category) {
    case 'file-read':
      return 'File Read';
    case 'file-write':
      return 'File Write';
    case 'file-search':
      return 'File Search';
    case 'execution':
      return 'Execution';
    case 'agent':
      return 'Agent';
    case 'web':
      return 'Web';
    case 'analysis':
      return 'Analysis';
    case 'other':
      return 'Tool';
  }
}

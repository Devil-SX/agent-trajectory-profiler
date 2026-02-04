/**
 * Mock data for Playwright tests
 */

import type {
  SessionListResponse,
  SessionDetailResponse,
  SessionStatisticsResponse,
  MessageRecord,
} from '../../src/types/session';

export const mockSessionList: SessionListResponse = {
  sessions: [
    {
      session_id: 'test-session-001',
      project_path: '/home/user/project',
      created_at: '2024-02-01T10:00:00Z',
      updated_at: '2024-02-01T11:30:00Z',
      total_messages: 25,
      total_tokens: 15000,
      git_branch: 'main',
      version: '1.0.0',
    },
    {
      session_id: 'test-session-002',
      project_path: '/home/user/project',
      created_at: '2024-02-02T14:00:00Z',
      updated_at: '2024-02-02T15:45:00Z',
      total_messages: 40,
      total_tokens: 25000,
      git_branch: 'feature/new-feature',
      version: '1.0.0',
    },
  ],
  count: 2,
};

const mockMessages: MessageRecord[] = [
  {
    sessionId: 'test-session-001',
    uuid: 'msg-001',
    timestamp: '2024-02-01T10:00:00Z',
    type: 'user',
    message: {
      role: 'user',
      content: 'Hello, can you help me with a bug?',
    },
  },
  {
    sessionId: 'test-session-001',
    uuid: 'msg-002',
    timestamp: '2024-02-01T10:01:00Z',
    type: 'assistant',
    message: {
      role: 'assistant',
      content: [
        {
          type: 'text',
          text: 'Of course! I\'d be happy to help you with the bug. Can you describe what issue you\'re experiencing?',
        },
      ],
      usage: {
        input_tokens: 100,
        output_tokens: 50,
      },
    },
  },
  {
    sessionId: 'test-session-001',
    uuid: 'msg-003',
    timestamp: '2024-02-01T10:02:00Z',
    type: 'user',
    message: {
      role: 'user',
      content: 'The app crashes when I click the submit button.',
    },
  },
  {
    sessionId: 'test-session-001',
    uuid: 'msg-004',
    timestamp: '2024-02-01T10:03:00Z',
    type: 'assistant',
    message: {
      role: 'assistant',
      content: [
        {
          type: 'text',
          text: 'Let me investigate the submit button code.',
        },
        {
          type: 'tool_use',
          id: 'tool-001',
          name: 'Read',
          input: {
            file_path: '/home/user/project/src/App.tsx',
          },
        },
      ],
      usage: {
        input_tokens: 120,
        output_tokens: 80,
      },
    },
  },
  {
    sessionId: 'test-session-001',
    uuid: 'msg-005',
    timestamp: '2024-02-01T10:04:00Z',
    type: 'assistant',
    message: {
      role: 'assistant',
      content: [
        {
          type: 'tool_result',
          tool_use_id: 'tool-001',
          content: 'File content here...',
        },
      ],
    },
  },
  {
    sessionId: 'test-session-001',
    uuid: 'msg-006',
    timestamp: '2024-02-01T10:05:00Z',
    type: 'assistant',
    message: {
      role: 'assistant',
      content: [
        {
          type: 'text',
          text: 'I found the issue! The submit handler is missing null checks. Let me fix that for you.',
        },
      ],
      usage: {
        input_tokens: 200,
        output_tokens: 30,
      },
    },
  },
];

export const mockSessionDetail: SessionDetailResponse = {
  session: {
    metadata: {
      session_id: 'test-session-001',
      project_path: '/home/user/project',
      git_branch: 'main',
      version: '1.0.0',
      created_at: '2024-02-01T10:00:00Z',
      updated_at: '2024-02-01T11:30:00Z',
      total_messages: 25,
      total_tokens: 15000,
    },
    messages: mockMessages,
  },
};

export const mockSessionStatistics: SessionStatisticsResponse = {
  session_id: 'test-session-001',
  statistics: {
    message_count: 25,
    user_message_count: 10,
    assistant_message_count: 15,
    system_message_count: 0,
    total_tokens: 15000,
    total_input_tokens: 10000,
    total_output_tokens: 5000,
    cache_read_tokens: 2000,
    cache_creation_tokens: 500,
    tool_calls: [
      {
        tool_name: 'Read',
        count: 15,
        total_tokens: 3000,
        success_count: 14,
        error_count: 1,
      },
      {
        tool_name: 'Edit',
        count: 8,
        total_tokens: 2000,
        success_count: 8,
        error_count: 0,
      },
      {
        tool_name: 'Bash',
        count: 5,
        total_tokens: 1500,
        success_count: 4,
        error_count: 1,
      },
    ],
    total_tool_calls: 28,
    subagent_count: 2,
    subagent_sessions: {
      Explore: 1,
      'test-runner': 1,
    },
    session_duration_seconds: 5400,
    first_message_time: '2024-02-01T10:00:00Z',
    last_message_time: '2024-02-01T11:30:00Z',
  },
};

/**
 * Mock server setup for Playwright tests
 */

import { Page } from '@playwright/test';
import { mockSessionList, mockSessionDetail, mockSessionStatistics } from './mockData';

/**
 * Setup mock API responses for tests
 */
export async function setupMockApi(page: Page) {
  const mockAnalyticsOverview = {
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total_sessions: 2,
    total_messages: 65,
    total_tokens: 40000,
    total_tool_calls: 18,
    total_input_tokens: 15000,
    total_output_tokens: 22000,
    total_cache_read_tokens: 2000,
    total_cache_creation_tokens: 1000,
    total_trajectory_file_size_bytes: 81920,
    total_chars: 120000,
    total_user_chars: 28000,
    total_model_chars: 76000,
    total_tool_chars: 16000,
    total_cjk_chars: 4200,
    total_latin_chars: 102000,
    total_other_chars: 13800,
    yield_ratio_tokens_mean: 2.5,
    yield_ratio_tokens_median: 2.4,
    yield_ratio_tokens_p90: 3.1,
    yield_ratio_chars_mean: 2.7,
    yield_ratio_chars_median: 2.6,
    yield_ratio_chars_p90: 3.3,
    avg_tokens_per_second_mean: 15.2,
    avg_tokens_per_second_median: 14.9,
    avg_tokens_per_second_p90: 22.8,
    read_tokens_per_second_mean: 4.2,
    read_tokens_per_second_median: 4.0,
    read_tokens_per_second_p90: 6.1,
    output_tokens_per_second_mean: 9.5,
    output_tokens_per_second_median: 9.2,
    output_tokens_per_second_p90: 14.0,
    cache_tokens_per_second_mean: 1.5,
    cache_tokens_per_second_median: 1.4,
    cache_tokens_per_second_p90: 2.2,
    cache_read_tokens_per_second_mean: 1.0,
    cache_read_tokens_per_second_median: 0.9,
    cache_read_tokens_per_second_p90: 1.5,
    cache_creation_tokens_per_second_mean: 0.5,
    cache_creation_tokens_per_second_median: 0.5,
    cache_creation_tokens_per_second_p90: 0.8,
    avg_automation_ratio: 2.1,
    avg_session_duration_seconds: 4600,
    model_time_seconds: 5300,
    tool_time_seconds: 2800,
    user_time_seconds: 1900,
    inactive_time_seconds: 600,
    day_model_time_seconds: 4100,
    day_tool_time_seconds: 1900,
    day_user_time_seconds: 1300,
    day_inactive_time_seconds: 300,
    night_model_time_seconds: 1200,
    night_tool_time_seconds: 900,
    night_user_time_seconds: 600,
    night_inactive_time_seconds: 300,
    active_time_ratio: 0.93,
    model_timeout_count: 1,
    bottleneck_distribution: [
      { key: 'model', label: 'Model', count: 1, value: 1, percent: 50 },
      { key: 'tool', label: 'Tool', count: 1, value: 1, percent: 50 },
    ],
    top_projects: [
      {
        project_path: '/home/user/project',
        project_name: 'project',
        sessions: 2,
        total_tokens: 40000,
        total_messages: 65,
        percent_sessions: 100,
        percent_tokens: 100,
      },
    ],
    top_tools: [
      {
        tool_name: 'Edit',
        total_calls: 9,
        sessions_using_tool: 2,
        error_count: 1,
        avg_latency_seconds: 0.28,
        percent_of_tool_calls: 50,
      },
    ],
  };

  const mockAutomationDistribution = {
    dimension: 'automation_band',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total: 2,
    buckets: [
      { key: 'medium', label: 'Medium', count: 1, value: 1, percent: 50 },
      { key: 'high', label: 'High', count: 1, value: 1, percent: 50 },
    ],
  };

  const mockSessionShareDistribution = {
    dimension: 'session_token_share',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    total: 2,
    buckets: [
      { key: 'test-session-001', label: 'test-session-001', count: 1, value: 23000, percent: 57.5 },
      { key: 'test-session-002', label: 'test-session-002', count: 1, value: 17000, percent: 42.5 },
    ],
  };

  const mockAnalyticsTimeseries = {
    interval: 'day',
    start_date: '2026-02-20',
    end_date: '2026-02-27',
    points: [
      { period: '2026-02-26', sessions: 1, tokens: 17000, tool_calls: 7, avg_automation_ratio: 1.8, avg_duration_seconds: 3900 },
      { period: '2026-02-27', sessions: 1, tokens: 23000, tool_calls: 11, avg_automation_ratio: 2.4, avg_duration_seconds: 5300 },
    ],
  };

  const mockSyncStatus = {
    total_files: 22,
    total_sessions: 2,
    last_parsed_at: '2026-02-27T01:02:03.000Z',
    sync_running: false,
    last_sync: {
      status: 'completed',
      trigger: 'manual',
      started_at: '2026-02-27T01:01:00.000Z',
      finished_at: '2026-02-27T01:02:00.000Z',
      parsed: 5,
      skipped: 10,
      errors: 0,
      total_files_scanned: 15,
      total_file_size_bytes: 10240,
      ecosystems: [
        {
          ecosystem: 'claude_code',
          files_scanned: 10,
          file_size_bytes: 8192,
          parsed: 4,
          skipped: 6,
          errors: 0,
        },
        {
          ecosystem: 'codex',
          files_scanned: 5,
          file_size_bytes: 2048,
          parsed: 1,
          skipped: 4,
          errors: 0,
        },
      ],
      error_samples: [],
    },
  };

  // Mock sessions list endpoint
  await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionList),
    });
  });

  // Mock session detail endpoint
  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionDetail),
    });
  });

  // Mock session statistics endpoint
  await page.route('**/api/sessions/test-session-001/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionStatistics),
    });
  });

  // Mock second session detail endpoint
  await page.route('**/api/sessions/test-session-002', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionDetail,
        session: {
          ...mockSessionDetail.session,
          metadata: {
            ...mockSessionDetail.session.metadata,
            session_id: 'test-session-002',
          },
        },
      }),
    });
  });

  // Mock second session statistics endpoint
  await page.route('**/api/sessions/test-session-002/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionStatistics,
        session_id: 'test-session-002',
      }),
    });
  });

  await page.route(/\/api\/sync\/status(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus),
    });
  });

  await page.route(/\/api\/sync\/run(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus.last_sync),
    });
  });

  await page.route(/\/api\/analytics\/overview(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAnalyticsOverview),
    });
  });

  await page.route(/\/api\/analytics\/distribution(?:s)?(?:\?.*)?$/, async (route) => {
    const url = new URL(route.request().url());
    const dimension = url.searchParams.get('dimension');
    const payload = dimension === 'session_token_share'
      ? mockSessionShareDistribution
      : mockAutomationDistribution;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });

  await page.route(/\/api\/analytics\/timeseries(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockAnalyticsTimeseries),
    });
  });
}

/**
 * E2E tests for cross-session file size and character metrics.
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@full Cross Session Char Metrics', () => {
  test('should render trajectory size and CJK/Latin character totals in overview', async ({ page }) => {
    await setupMockApi(page);

    await page.route(/\/api\/analytics\/overview(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          start_date: '2026-02-20',
          end_date: '2026-02-26',
          total_sessions: 12,
          total_messages: 540,
          total_tokens: 320000,
          total_tool_calls: 860,
          total_input_tokens: 180000,
          total_output_tokens: 140000,
          total_cache_read_tokens: 22000,
          total_cache_creation_tokens: 9000,
          total_trajectory_file_size_bytes: 987654,
          total_chars: 450000,
          total_user_chars: 120000,
          total_model_chars: 250000,
          total_tool_chars: 80000,
          total_cjk_chars: 90000,
          total_latin_chars: 330000,
          total_other_chars: 30000,
          yield_ratio_tokens_mean: 2.4,
          yield_ratio_tokens_median: 2.2,
          yield_ratio_tokens_p90: 3.1,
          yield_ratio_chars_mean: 3.5,
          yield_ratio_chars_median: 3.3,
          yield_ratio_chars_p90: 4.2,
          avg_tokens_per_second_mean: 12.4,
          avg_tokens_per_second_median: 11.8,
          avg_tokens_per_second_p90: 15.9,
          read_tokens_per_second_mean: 7.2,
          read_tokens_per_second_median: 6.9,
          read_tokens_per_second_p90: 9.4,
          output_tokens_per_second_mean: 5.2,
          output_tokens_per_second_median: 5.0,
          output_tokens_per_second_p90: 6.5,
          cache_tokens_per_second_mean: 1.6,
          cache_tokens_per_second_median: 1.4,
          cache_tokens_per_second_p90: 2.2,
          cache_read_tokens_per_second_mean: 1.1,
          cache_read_tokens_per_second_median: 1.0,
          cache_read_tokens_per_second_p90: 1.5,
          cache_creation_tokens_per_second_mean: 0.5,
          cache_creation_tokens_per_second_median: 0.4,
          cache_creation_tokens_per_second_p90: 0.7,
          avg_automation_ratio: 2.5,
          avg_session_duration_seconds: 4200,
          model_time_seconds: 36000,
          tool_time_seconds: 22000,
          user_time_seconds: 14000,
          inactive_time_seconds: 8000,
          day_model_time_seconds: 25000,
          day_tool_time_seconds: 14000,
          day_user_time_seconds: 9000,
          day_inactive_time_seconds: 3000,
          night_model_time_seconds: 11000,
          night_tool_time_seconds: 8000,
          night_user_time_seconds: 5000,
          night_inactive_time_seconds: 5000,
          active_time_ratio: 0.8788,
          model_timeout_count: 3,
          bottleneck_distribution: [
            { key: 'model', label: 'Model', count: 7, value: 7, percent: 58.3 },
            { key: 'tool', label: 'Tool', count: 4, value: 4, percent: 33.3 },
            { key: 'user', label: 'User', count: 1, value: 1, percent: 8.4 },
          ],
          top_projects: [],
          top_tools: [],
        }),
      });
    });

    await page.route(/\/api\/analytics\/distributions(\?.*)?$/, async (route) => {
      const url = route.request().url();
      const payload = url.includes('dimension=session_token_share')
        ? {
            dimension: 'session_token_share',
            start_date: '2026-02-20',
            end_date: '2026-02-26',
            total: 100,
            buckets: [],
          }
        : {
            dimension: 'automation_band',
            start_date: '2026-02-20',
            end_date: '2026-02-26',
            total: 12,
            buckets: [],
          };
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      });
    });

    await page.route(/\/api\/analytics\/timeseries(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          interval: 'day',
          start_date: '2026-02-20',
          end_date: '2026-02-26',
          points: [
            {
              period: '2026-02-20',
              sessions: 2,
              tokens: 43000,
              tool_calls: 120,
              avg_automation_ratio: 2.1,
              avg_duration_seconds: 3900,
            },
          ],
        }),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await page.waitForSelector('.cross-session-overview', { timeout: 10000 });

    await expect(page.locator('.kpi-card', { hasText: 'Token volume' })).toContainText(
      'Trajectory size: 987,654 bytes'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Token volume' })).toContainText(
      'Chars (CJK/Latin): 90,000 / 330,000'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Automation efficiency' })).toContainText(
      'Token yield (mean/median/p90): 2.40x / 2.20x / 3.10x'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Automation efficiency' })).toContainText(
      'Char yield (mean/median/p90): 3.50x / 3.30x / 4.20x'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Tool execution' })).toContainText(
      'Model tok/s (mean/median/p90): 12.40 / 11.80 / 15.90'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Tool execution' })).toContainText(
      'Read/Output tok/s mean: 7.20 / 5.20'
    );
    await expect(page.locator('.kpi-card', { hasText: 'Tool execution' })).toContainText(
      'Cache tok/s mean: 1.60 (1.10 / 0.50)'
    );
  });
});

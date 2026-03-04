import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Day Night Analytics', () => {
  test('renders day/night chart and table with consistent totals', async ({ page }) => {
    await setupMockApi(page);

    await page.route(/\/api\/analytics\/overview(\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          start_date: '2026-02-20',
          end_date: '2026-02-26',
          total_sessions: 10,
          total_messages: 320,
          total_tokens: 180000,
          total_tool_calls: 430,
          total_input_tokens: 90000,
          total_output_tokens: 74000,
          total_tool_output_tokens: 18000,
          total_cache_read_tokens: 11000,
          total_cache_creation_tokens: 5000,
          total_trajectory_file_size_bytes: 500000,
          total_chars: 260000,
          total_user_chars: 82000,
          total_model_chars: 140000,
          total_tool_chars: 38000,
          total_cjk_chars: 70000,
          total_latin_chars: 170000,
          total_other_chars: 20000,
          yield_ratio_tokens_mean: 2.0,
          yield_ratio_tokens_median: 1.9,
          yield_ratio_tokens_p90: 2.6,
          yield_ratio_chars_mean: 2.7,
          yield_ratio_chars_median: 2.6,
          yield_ratio_chars_p90: 3.3,
          leverage_tokens_mean: 2.0,
          leverage_tokens_median: 1.9,
          leverage_tokens_p90: 2.6,
          leverage_chars_mean: 2.7,
          leverage_chars_median: 2.6,
          leverage_chars_p90: 3.3,
          avg_tokens_per_second_mean: 10.2,
          avg_tokens_per_second_median: 9.8,
          avg_tokens_per_second_p90: 12.6,
          read_tokens_per_second_mean: 4.8,
          read_tokens_per_second_median: 4.6,
          read_tokens_per_second_p90: 6.2,
          output_tokens_per_second_mean: 5.4,
          output_tokens_per_second_median: 5.2,
          output_tokens_per_second_p90: 6.8,
          cache_tokens_per_second_mean: 1.3,
          cache_tokens_per_second_median: 1.2,
          cache_tokens_per_second_p90: 1.8,
          cache_read_tokens_per_second_mean: 0.9,
          cache_read_tokens_per_second_median: 0.8,
          cache_read_tokens_per_second_p90: 1.2,
          cache_creation_tokens_per_second_mean: 0.4,
          cache_creation_tokens_per_second_median: 0.4,
          cache_creation_tokens_per_second_p90: 0.6,
          avg_automation_ratio: 2.2,
          avg_session_duration_seconds: 3600,
          model_time_seconds: 4500,
          tool_time_seconds: 2400,
          user_time_seconds: 1500,
          inactive_time_seconds: 1200,
          day_model_time_seconds: 3600,
          day_tool_time_seconds: 1800,
          day_user_time_seconds: 900,
          day_inactive_time_seconds: 1800,
          night_model_time_seconds: 900,
          night_tool_time_seconds: 600,
          night_user_time_seconds: 600,
          night_inactive_time_seconds: 0,
          coverage_total_window_seconds: 604800,
          coverage_day_window_seconds: 403200,
          coverage_night_window_seconds: 201600,
          day_model_coverage_seconds: 100800,
          day_tool_coverage_seconds: 50400,
          day_user_coverage_seconds: 25200,
          night_model_coverage_seconds: 25200,
          night_tool_coverage_seconds: 10080,
          night_user_coverage_seconds: 5040,
          active_time_ratio: 0.8889,
          model_timeout_count: 2,
          bottleneck_distribution: [
            { key: 'model', label: 'Model', count: 6, value: 6, percent: 60 },
            { key: 'tool', label: 'Tool', count: 3, value: 3, percent: 30 },
            { key: 'user', label: 'User', count: 1, value: 1, percent: 10 },
          ],
          top_projects: [],
          top_tools: [],
        }),
      });
    });

    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await page.waitForSelector('.day-night-card', { timeout: 10000 });

    await expect(page.locator('.day-night-note')).toContainText('01:00-09:00');
    await expect(page.locator('.day-night-chart')).toBeVisible();
    await expect(page.locator('.day-night-summary')).toContainText('Day total: 2h 15m');
    await expect(page.locator('.day-night-summary')).toContainText('Night total: 35m');

    const dayRow = page.locator('.day-night-table tbody tr').nth(0);
    await expect(dayRow).toContainText('Day');
    await expect(dayRow).toContainText('2h 15m');
    await expect(dayRow).toContainText('79.4%');

    const nightRow = page.locator('.day-night-table tbody tr').nth(1);
    await expect(nightRow).toContainText('Night');
    await expect(nightRow).toContainText('35m');
    await expect(nightRow).toContainText('20.6%');

    await expect(page.locator('.day-night-coverage-table')).toBeVisible();
    const dayCoverageRow = page.locator('.day-night-coverage-table tbody tr').nth(0);
    await expect(dayCoverageRow).toContainText('25.0%');

    await page.getByRole('button', { name: 'Exclude inactive' }).click();
    await expect(page.locator('.day-night-summary')).toContainText('Day total: 1h 45m');
    await expect(page.locator('.day-night-summary')).toContainText('Night total: 35m');
    await expect(dayRow).toContainText('75.0%');
    await expect(nightRow).toContainText('25.0%');
  });
});

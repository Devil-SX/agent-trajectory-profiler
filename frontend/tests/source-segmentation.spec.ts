import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Cross-session source segmentation', () => {
  test('source filter links role/source table and source comparison table', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('[data-testid="role-source-table"]', { timeout: 10000 });

    const roleSourceRows = page.locator('[data-testid^="role-source-row-"]');
    await expect(roleSourceRows).toHaveCount(6);

    await page.getByTestId('source-filter-codex').click();
    await expect(page.locator('[data-testid="source-filter-codex"]')).toHaveClass(/active/);

    await expect(roleSourceRows).toHaveCount(3);
    await expect(page.locator('[data-testid="role-source-primary-bottleneck"]')).toContainText(
      'Codex'
    );

    const comparisonCard = page.locator('.overview-card:has-text("Source comparison table")');
    await expect(comparisonCard).toContainText('Codex');
    await expect(comparisonCard).not.toContainText('Claude Code');

    const capabilityNotes = page.getByTestId('cross-capability-notes');
    await expect(capabilityNotes).toBeVisible();
    await expect(capabilityNotes).toContainText('Time-based metrics');
  });

  test('supports role/source dimension switch and metric switch', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('[data-testid="role-source-table"]', { timeout: 10000 });

    await page.getByTestId('role-source-dimension-role').click();
    await expect(page.getByTestId('role-source-dimension-role')).toHaveClass(/active/);

    await page.getByTestId('role-source-metric-errors').click();
    await expect(page.getByTestId('role-source-metric-errors')).toHaveClass(/active/);

    await expect(page.locator('[data-testid="role-source-table"]')).toBeVisible();
    await expect(page.locator('[data-testid^="role-source-row-"]')).toHaveCount(6);
  });

  test('falls back gracefully when role/source data is empty', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute(/\/api\/analytics\/overview(?:\?.*)?$/);
    await page.route(/\/api\/analytics\/overview(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          start_date: '2026-02-20',
          end_date: '2026-02-27',
          total_sessions: 0,
          total_messages: 0,
          total_tokens: 0,
          total_tool_calls: 0,
          total_input_tokens: 0,
          total_output_tokens: 0,
          total_tool_output_tokens: 0,
          total_cache_read_tokens: 0,
          total_cache_creation_tokens: 0,
          total_trajectory_file_size_bytes: 0,
          total_chars: 0,
          total_user_chars: 0,
          total_model_chars: 0,
          total_tool_chars: 0,
          total_cjk_chars: 0,
          total_latin_chars: 0,
          total_other_chars: 0,
          yield_ratio_tokens_mean: 0,
          yield_ratio_tokens_median: 0,
          yield_ratio_tokens_p90: 0,
          yield_ratio_chars_mean: 0,
          yield_ratio_chars_median: 0,
          yield_ratio_chars_p90: 0,
          leverage_tokens_mean: 0,
          leverage_tokens_median: 0,
          leverage_tokens_p90: 0,
          leverage_chars_mean: 0,
          leverage_chars_median: 0,
          leverage_chars_p90: 0,
          avg_tokens_per_second_mean: 0,
          avg_tokens_per_second_median: 0,
          avg_tokens_per_second_p90: 0,
          read_tokens_per_second_mean: 0,
          read_tokens_per_second_median: 0,
          read_tokens_per_second_p90: 0,
          output_tokens_per_second_mean: 0,
          output_tokens_per_second_median: 0,
          output_tokens_per_second_p90: 0,
          cache_tokens_per_second_mean: 0,
          cache_tokens_per_second_median: 0,
          cache_tokens_per_second_p90: 0,
          cache_read_tokens_per_second_mean: 0,
          cache_read_tokens_per_second_median: 0,
          cache_read_tokens_per_second_p90: 0,
          cache_creation_tokens_per_second_mean: 0,
          cache_creation_tokens_per_second_median: 0,
          cache_creation_tokens_per_second_p90: 0,
          avg_automation_ratio: 0,
          avg_session_duration_seconds: 0,
          model_time_seconds: 0,
          tool_time_seconds: 0,
          user_time_seconds: 0,
          inactive_time_seconds: 0,
          day_model_time_seconds: 0,
          day_tool_time_seconds: 0,
          day_user_time_seconds: 0,
          day_inactive_time_seconds: 0,
          night_model_time_seconds: 0,
          night_tool_time_seconds: 0,
          night_user_time_seconds: 0,
          night_inactive_time_seconds: 0,
          active_time_ratio: 0,
          model_timeout_count: 0,
          source_breakdown: [],
          role_source_breakdown: [],
          primary_bottleneck_key: null,
          primary_bottleneck_label: null,
          primary_bottleneck_source: null,
          primary_bottleneck_role: null,
          bottleneck_distribution: [],
          top_projects: [],
          top_tools: [],
          control_plane: {
            logical_sessions: 0,
            physical_sessions: 0,
            files: {
              total_files: 0,
              parsed_files: 0,
              error_files: 0,
              pending_files: 0,
              total_tracked_file_size_bytes: 0,
              total_trajectory_file_size_bytes: 0,
              last_parsed_at: null,
            },
            sync_running: false,
            last_sync: {
              status: 'idle',
              trigger: 'startup',
              started_at: null,
              finished_at: null,
              parsed: 0,
              skipped: 0,
              errors: 0,
              total_files_scanned: 0,
              total_file_size_bytes: 0,
              ecosystems: [],
              error_samples: [],
            },
          },
          runtime_plane: {
            total_messages: 0,
            total_tokens: 0,
            total_tool_calls: 0,
            total_input_tokens: 0,
            total_output_tokens: 0,
            total_tool_output_tokens: 0,
            total_cache_read_tokens: 0,
            total_cache_creation_tokens: 0,
            total_chars: 0,
            total_user_chars: 0,
            total_model_chars: 0,
            total_tool_chars: 0,
            total_cjk_chars: 0,
            total_latin_chars: 0,
            total_other_chars: 0,
            yield_ratio_tokens_mean: 0,
            yield_ratio_tokens_median: 0,
            yield_ratio_tokens_p90: 0,
            yield_ratio_chars_mean: 0,
            yield_ratio_chars_median: 0,
            yield_ratio_chars_p90: 0,
            leverage_tokens_mean: 0,
            leverage_tokens_median: 0,
            leverage_tokens_p90: 0,
            leverage_chars_mean: 0,
            leverage_chars_median: 0,
            leverage_chars_p90: 0,
            avg_tokens_per_second_mean: 0,
            avg_tokens_per_second_median: 0,
            avg_tokens_per_second_p90: 0,
            read_tokens_per_second_mean: 0,
            read_tokens_per_second_median: 0,
            read_tokens_per_second_p90: 0,
            output_tokens_per_second_mean: 0,
            output_tokens_per_second_median: 0,
            output_tokens_per_second_p90: 0,
            cache_tokens_per_second_mean: 0,
            cache_tokens_per_second_median: 0,
            cache_tokens_per_second_p90: 0,
            cache_read_tokens_per_second_mean: 0,
            cache_read_tokens_per_second_median: 0,
            cache_read_tokens_per_second_p90: 0,
            cache_creation_tokens_per_second_mean: 0,
            cache_creation_tokens_per_second_median: 0,
            cache_creation_tokens_per_second_p90: 0,
            avg_automation_ratio: 0,
            avg_session_duration_seconds: 0,
            model_time_seconds: 0,
            tool_time_seconds: 0,
            user_time_seconds: 0,
            inactive_time_seconds: 0,
            day_model_time_seconds: 0,
            day_tool_time_seconds: 0,
            day_user_time_seconds: 0,
            day_inactive_time_seconds: 0,
            night_model_time_seconds: 0,
            night_tool_time_seconds: 0,
            night_user_time_seconds: 0,
            night_inactive_time_seconds: 0,
            active_time_ratio: 0,
            model_timeout_count: 0,
            source_breakdown: [],
            role_source_breakdown: [],
            primary_bottleneck_key: null,
            primary_bottleneck_label: null,
            primary_bottleneck_source: null,
            primary_bottleneck_role: null,
            bottleneck_distribution: [],
            top_projects: [],
            top_tools: [],
          },
        }),
      });
    });

    await page.goto('/');
    await page.waitForSelector('[data-testid="role-source-empty"]', { timeout: 10000 });
    await expect(page.getByTestId('role-source-empty')).toBeVisible();
  });
});

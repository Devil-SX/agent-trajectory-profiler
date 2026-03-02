/**
 * E2E tests for time breakdown analytics presentation.
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';
import { mockSessionStatistics } from './fixtures/mockData';

test.describe('@full Time Breakdown Analytics', () => {
  test('should show Model/Tool/User sections and active-time-only pie scope', async ({ page }) => {
    await setupMockApi(page);

    await page.route(/\/api\/sessions\/test-session-(001|002)\/statistics$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSessionStatistics,
          statistics: {
            ...mockSessionStatistics.statistics,
            time_breakdown: {
              total_model_time_seconds: 120,
              total_tool_time_seconds: 60,
              total_user_time_seconds: 20,
              total_inactive_time_seconds: 100,
              total_active_time_seconds: 200,
              model_time_percent: 60,
              tool_time_percent: 30,
              user_time_percent: 10,
              inactive_time_percent: 33.3,
              active_time_ratio: 0.6667,
              inactivity_threshold_seconds: 1800,
              user_interaction_count: 5,
              interactions_per_hour: 90,
              model_timeout_count: 1,
              model_timeout_threshold_seconds: 600,
            },
          },
        }),
      });
    });

    await page.goto('/');
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 10000 });
    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await page.getByRole('button', { name: 'Statistics' }).click();
    await page.waitForSelector('.time-breakdown-chart', { timeout: 10000 });

    await expect(page.locator('.active-ratio-text')).toContainText('66.7%');
    await expect(page.locator('.time-category-card')).toHaveCount(3);
    await expect(page.locator('.time-category-card').first()).toContainText('Model');
    await expect(page.locator('.time-category-card').nth(1)).toContainText('Tool');
    await expect(page.locator('.time-category-card').nth(2)).toContainText('User');

    await expect(page.locator('.pie-scope-note')).toContainText('active time only');
    await expect(page.locator('.pie-scope-list .pie-scope-item')).toHaveCount(3);
    await expect(page.locator('.pie-scope-list')).not.toContainText('Inactive');
  });
});

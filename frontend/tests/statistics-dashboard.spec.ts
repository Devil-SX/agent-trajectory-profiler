/**
 * E2E tests for StatisticsDashboard rendering and interaction.
 */

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';
import { mockSessionStatistics } from './fixtures/mockData';

async function openStatisticsTab(page: Page): Promise<void> {
  await page.waitForSelector('.tab-button', { timeout: 10000 });
  await page.getByRole('button', { name: 'Statistics' }).click();
  await page.waitForSelector('.statistics-dashboard', { timeout: 10000 });
}

test.describe('@smoke Statistics Dashboard - Tool Errors', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);

    await page.route(/\/api\/sessions\/test-session-(001|002)\/statistics$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ...mockSessionStatistics,
          statistics: {
            ...mockSessionStatistics.statistics,
            tool_error_records: [
              {
                timestamp: '2026-02-26T08:30:00Z',
                tool_name: 'Edit',
                category: 'file_not_found',
                matched_rule: 'file_not_found',
                preview: "Error: string not found in '/tmp/app.ts'",
                detail: "Error: string not found in '/tmp/app.ts'",
              },
              {
                timestamp: '2026-02-26T08:31:00Z',
                tool_name: 'Bash',
                category: 'uncategorized',
                matched_rule: null,
                preview: 'custom runtime error from unknown wrapper',
                detail: 'custom runtime error from unknown wrapper',
              },
            ],
            tool_error_category_counts: {
              file_not_found: 1,
              uncategorized: 1,
            },
            error_taxonomy_version: '1.0.0',
          },
        }),
      });
    });
  });

  test('should render error timeline with expandable details', async ({ page }) => {
    await page.goto('/');
    await openStatisticsTab(page);
    await expect(page.locator('.dashboard-title')).toHaveText('Session Metrics');
    await expect(page.locator('.card-title', { hasText: 'Tool Error Timeline' })).toBeVisible();

    const categoryChips = page.locator('.error-category-chip');
    await expect(categoryChips).toHaveCount(2);
    await expect(categoryChips.first()).toContainText('file_not_found');

    const mainRows = page.locator('.error-timeline-table tbody tr:not(.error-detail-row)');
    await expect(mainRows).toHaveCount(2);

    const firstExpand = page.locator('.error-expand-button').first();
    await expect(firstExpand).toHaveText('Expand');
    await firstExpand.click();

    const detailRow = page.locator('.error-detail-row').first();
    await expect(detailRow).toBeVisible();
    await expect(detailRow).toContainText("string not found in '/tmp/app.ts'");

    await firstExpand.click();
    await expect(firstExpand).toHaveText('Expand');
  });

  test('should expose horizontal scroll container for dense error tables', async ({ page }) => {
    await page.setViewportSize({ width: 960, height: 720 });
    await page.goto('/');
    await openStatisticsTab(page);
    await page.waitForSelector('.error-timeline-table', { timeout: 10000 });

    const overflowX = await page.locator('.error-timeline-table').evaluate((table) =>
      window.getComputedStyle(table.parentElement as HTMLElement).overflowX
    );
    expect(['auto', 'scroll']).toContain(overflowX);
  });
});

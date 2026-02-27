/**
 * E2E tests for two-layer navigation:
 * Overview (cross-session + table) -> Session Detail.
 */

import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

async function waitForOverview(page: import('@playwright/test').Page) {
  await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
  await page.waitForSelector('.advanced-analytics', { timeout: 10000 });
  await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 10000 });
}

test.describe('@smoke Navigation IA - Overview then Session Detail', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForOverview(page);
  });

  test('lands on overview by default and shows both analytics + session table', async ({ page }) => {
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(
      /active/
    );
    await expect(page.locator('.advanced-analytics')).toBeVisible();
    await expect(page.locator('.session-table')).toBeVisible();

    const url = page.url();
    expect(url).toContain('view=overview');
  });

  test('drills down from table row into session detail and supports in-page back', async ({ page }) => {
    await page.locator('tr[data-session-id="test-session-002"]').click();

    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
    await expect(page.locator('.detail-back-button')).toBeVisible();
    await expect(page.locator('.message-timeline, .statistics-dashboard').first()).toBeVisible();
    await expect(page).toHaveURL(/session=test-session-002/);

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await waitForOverview(page);
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(
      /active/
    );
    await expect(page).toHaveURL(/view=overview/);
  });
});

test.describe('@full Navigation history + URL restore', () => {
  test('browser back/forward follows overview-detail route state', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForOverview(page);

    await page.locator('tr[data-session-id="test-session-001"]').click();
    await expect(page).toHaveURL(/session=test-session-001/);
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);

    await page.goBack();
    await waitForOverview(page);
    await expect(page).toHaveURL(/view=overview/);

    await page.goForward();
    await expect(page).toHaveURL(/session=test-session-001/);
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
  });

  test('session deep-link restores detail view and tab from URL', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/?session=test-session-001&tab=statistics');

    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
    await expect(page.getByRole('button', { name: 'Statistics' })).toHaveClass(/active/);
    await expect(page.locator('.statistics-dashboard')).toBeVisible();

    await page.reload();
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
    await expect(page.getByRole('button', { name: 'Statistics' })).toHaveClass(/active/);
    await expect(page.locator('.statistics-dashboard')).toBeVisible();
  });
});

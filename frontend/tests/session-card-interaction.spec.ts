import { test, expect, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

async function openOverview(page: Page) {
  await setupMockApi(page);
  await page.goto('/');
  await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
  await page.waitForSelector('.session-table tbody tr', { timeout: 10000 });
}

test.describe('@full Session selection flow', () => {
  test('keeps URL-selected session as the default active session', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/?session=test-session-001');

    await page.waitForSelector('.detail-session-caption code', { timeout: 10000 });
    await expect(page.locator('.detail-session-caption code')).toContainText('test-session-001');
    await expect(page.locator('.message-timeline')).toBeVisible();
  });

  test('supports switching selected session from overview list', async ({ page }) => {
    await openOverview(page);

    await page.locator('tr[data-session-id="test-session-001"]').click();
    await expect(page.locator('.detail-session-caption code')).toContainText('test-session-001');

    await page.locator('.detail-back-button').click();
    await page.waitForSelector('.session-table tbody tr', { timeout: 10000 });

    await page.locator('tr[data-session-id="test-session-002"]').click();
    await expect(page.locator('.detail-session-caption code')).toContainText('test-session-002');
  });

  test('shows metadata and statistics for the selected session', async ({ page }) => {
    await openOverview(page);

    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.locator('.view-tabs--primary .tab-button').nth(1).click();

    await expect(page.locator('.metadata-sidebar')).toBeVisible();
    await expect(page.locator('.metadata-sidebar .sidebar-title')).toContainText('Session Metadata');

    await page.locator('.view-tabs--secondary .tab-button').nth(1).click();
    await expect(page.locator('.statistics-dashboard')).toBeVisible();
  });
});

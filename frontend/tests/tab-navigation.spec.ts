/**
 * E2E tests for top-level navigation and tab state persistence.
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

async function waitForNavigationReady(page: import('@playwright/test').Page) {
  await page.waitForSelector('.view-tabs--primary', { timeout: 10000 });
  await page.waitForSelector('.view-tabs--secondary', { timeout: 10000 });
  await page.waitForSelector('.session-table tbody tr.selected, .session-card--selected', {
    timeout: 10000,
  });
}

test.describe('@smoke Navigation IA - Session Detail & Cross-Session', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForNavigationReady(page);
  });

  test('should open Cross-Session Analytics without requiring selected session', async ({
    page,
  }) => {
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(
      /active/
    );
    await expect(page.locator('.advanced-analytics').first()).toBeVisible();
    await expect(page.locator('.analytics-title')).toHaveText('Cross-Session Analytics');

    // Force no visible sessions -> selected session should become null, but cross-session
    // analytics should remain available.
    await page.locator('.search-input').fill('__no_match__');
    await page.waitForTimeout(500);
    await expect(page.locator('.advanced-analytics').first()).toBeVisible();
    await expect(page.locator('.advanced-analytics')).toContainText(
      'Cross-session analytics is available without selecting a session.'
    );
  });

  test('should keep Session Detail sub-tab when switching selected session', async ({
    page,
  }) => {
    await page.getByRole('button', { name: 'Statistics' }).click();
    await expect(page.getByRole('button', { name: 'Statistics' })).toHaveClass(/active/);
    await expect(page.locator('.statistics-dashboard')).toBeVisible();

    await page.locator('tr[data-session-id="test-session-002"]').click();
    await expect(page.locator('tr[data-session-id="test-session-002"]')).toHaveClass(
      /selected/
    );

    await expect(page.getByRole('button', { name: 'Statistics' })).toHaveClass(/active/);
    await expect(page.locator('.statistics-dashboard')).toBeVisible();
  });

  test('should keep Cross-Session view active when switching sessions', async ({ page }) => {
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(
      /active/
    );

    await page.locator('tr[data-session-id="test-session-002"]').click();
    await expect(page.locator('tr[data-session-id="test-session-002"]')).toHaveClass(
      /selected/
    );

    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(
      /active/
    );
    await expect(page.locator('.advanced-analytics').first()).toBeVisible();
  });

  test('should default to table view and persist session list view preference', async ({
    page,
  }) => {
    await expect(page.getByRole('button', { name: 'Table View' })).toHaveClass(/active/);
    await expect(page.locator('.session-table')).toBeVisible();

    await page.getByRole('button', { name: 'Card View' }).click();
    await expect(page.getByRole('button', { name: 'Card View' })).toHaveClass(/active/);
    await expect(page.locator('.session-card').first()).toBeVisible();

    await page.reload();
    await waitForNavigationReady(page);
    await expect(page.getByRole('button', { name: 'Card View' })).toHaveClass(/active/);
    await expect(page.locator('.session-card').first()).toBeVisible();
  });
});

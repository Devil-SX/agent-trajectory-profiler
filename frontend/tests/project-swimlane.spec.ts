import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Project Swimlane', () => {
  test('supports multi-project comparison and swimlane rendering', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();

    await page.waitForSelector('.project-chip-group', { timeout: 10000 });
    const chips = page.locator('.project-chip');
    await expect(chips).toHaveCount(3);

    const comparisonRows = page.locator('.overview-card:has-text("Project comparison") tbody tr');
    await expect(comparisonRows).toHaveCount(3);

    await chips.nth(0).click();
    await expect(comparisonRows).toHaveCount(2);

    const swimlane = page.locator('.swimlane-table');
    await expect(swimlane).toBeVisible();
    await expect(swimlane.locator('thead th')).toHaveCount(3);
    await expect(swimlane.locator('tbody .swimlane-cell').first()).toBeVisible();
  });

  test('keeps swimlane usable on mobile viewport', async ({ page }) => {
    await setupMockApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await page.waitForSelector('.swimlane-wrapper', { timeout: 10000 });

    const overflowX = await page.locator('.swimlane-wrapper').evaluate((node) =>
      window.getComputedStyle(node).overflowX
    );
    expect(['auto', 'scroll']).toContain(overflowX);
    await expect(page.locator('.swimlane-table')).toBeVisible();
  });
});

import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Project Gantt Timeline', () => {
  test('supports multi-project comparison and gantt rendering with day/week switch', async ({ page }) => {
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

    const gantt = page.locator('.project-gantt-chart');
    await expect(gantt).toBeVisible();
    await expect(page.locator('.gantt-bar').first()).toBeVisible();

    await page.getByRole('button', { name: 'Week' }).click();
    await expect(page.locator('.project-gantt-granularity button.active')).toContainText('Week');
    await expect(page.locator('.gantt-bar').first()).toBeVisible();

    await expect(page.locator('.swimlane-table')).toHaveCount(0);
  });

  test('keeps gantt usable on mobile viewport', async ({ page }) => {
    await setupMockApi(page);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await page.waitForSelector('.gantt-wrapper', { timeout: 10000 });

    const overflowX = await page.locator('.gantt-wrapper').evaluate((node) =>
      window.getComputedStyle(node).overflowX
    );
    expect(['auto', 'scroll']).toContain(overflowX);
    await expect(page.locator('.project-gantt-chart')).toBeVisible();
  });
});

import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Cross-session source segmentation', () => {
  test('renders ecosystem distribution chart and comparison table', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.plane-section--control', { timeout: 10000 });
    await page.waitForSelector('.plane-section--runtime', { timeout: 10000 });

    const controlPlane = page.locator('.plane-section--control');
    await expect(controlPlane).toContainText('Control/Ingestion Plane');
    await expect(controlPlane).toContainText('Parsed');
    await expect(controlPlane).toContainText('Skipped');
    await expect(controlPlane).toContainText('Errors');

    const runtimePlane = page.locator('.plane-section--runtime');
    await expect(runtimePlane).toContainText('Runtime/Behavior Plane');
    await expect(runtimePlane).toContainText('Token volume');
    await expect(runtimePlane).not.toContainText('Parse status');

    await page.waitForSelector('.overview-card:has-text("Source ecosystem distribution")', {
      timeout: 10000,
    });

    const distributionCard = page.locator('.overview-card:has-text("Source ecosystem distribution")');
    await expect(distributionCard).toContainText('Sessions');
    await expect(distributionCard).toContainText('Tokens');

    const comparisonCard = page.locator('.overview-card:has-text("Source comparison table")');
    await expect(comparisonCard).toBeVisible();

    const rows = comparisonCard.locator('tbody tr');
    await expect(rows).toHaveCount(2);
    await expect(comparisonCard).toContainText('Claude Code');
    await expect(comparisonCard).toContainText('Codex');
  });
});

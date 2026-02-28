import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Cross-session source segmentation', () => {
  test('renders ecosystem distribution chart and comparison table', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

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

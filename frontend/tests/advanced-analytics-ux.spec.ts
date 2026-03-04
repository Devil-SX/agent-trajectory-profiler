import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('Advanced analytics readability contracts', () => {
  test('@smoke renders cross-session aggregates with stable semantic sections', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.advanced-analytics .analytics-title', { timeout: 10000 });
    await expect(page.locator('.advanced-analytics .analytics-title')).toHaveText('Cross-Session Analytics');

    const totalSessionsCard = page.locator('.kpi-card:has-text("Total sessions")');
    await expect(totalSessionsCard).toBeVisible();
    await expect(totalSessionsCard.locator('.kpi-value')).toHaveText('2');

    await expect(page.getByTestId('role-source-table')).toBeVisible();
    await expect(page.locator('[data-testid^="role-source-row-"]')).toHaveCount(6);

    const sourceComparisonCard = page.locator('.overview-card:has-text("Source comparison table")');
    await expect(sourceComparisonCard).toContainText('Claude Code');
    await expect(sourceComparisonCard).toContainText('Codex');
  });

  test('@full keeps cross-session analytics readable after detail roundtrip navigation', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.advanced-analytics .analytics-title', { timeout: 10000 });
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 10000 });

    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
    await expect(page.locator('.message-timeline')).toBeVisible();

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toHaveClass(/active/);
    await expect(page.locator('.advanced-analytics .analytics-title')).toHaveText('Cross-Session Analytics');
    await expect(page.locator('.kpi-card:has-text("Token volume") .kpi-value')).toContainText('40K');
    await expect(page.getByTestId('role-source-table')).toBeVisible();
  });
});

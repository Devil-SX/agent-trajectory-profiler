import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Metric glossary and help popovers', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.cross-session-overview', { timeout: 10000 });
  });

  test('shows glossary tooltip hint and expandable details with keyboard access', async ({ page }) => {
    const leverageTrigger = page.locator('[data-metric-help="leverage"] .metric-help__trigger').first();
    await expect(leverageTrigger).toBeVisible();
    await expect(leverageTrigger).toHaveAttribute('title', /output/i);

    await leverageTrigger.click();
    await expect(page.locator('.metric-help__panel')).toContainText('Formula');
    await expect(page.locator('.metric-help__panel')).toContainText('model output');

    await page.locator('.metric-help__close').first().click();
    await expect(page.locator('.metric-help__panel')).toHaveCount(0);

    const activeRatioTrigger = page.locator('[data-metric-help="active_ratio"] .metric-help__trigger').first();
    await activeRatioTrigger.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.metric-help__panel')).toContainText('Active Ratio');
  });

  test('renders glossary content in Chinese after locale switch', async ({ page }) => {
    await page.locator('#language-mode-select').selectOption('zh-CN');

    const leverageTrigger = page.locator('[data-metric-help="leverage"] .metric-help__trigger').first();
    await leverageTrigger.click();

    const panel = page.locator('.metric-help__panel').first();
    await expect(panel).toContainText('杠杆');
    await expect(panel).toContainText('公式');
    await expect(panel).toContainText('输入来源');
  });
});

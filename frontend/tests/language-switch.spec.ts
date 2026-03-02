import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke i18n language switch', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
  });

  test('switches EN/ZH labels and persists locale after reload', async ({ page }) => {
    const languageSelect = page.locator('#language-mode-select');
    const syncPanelTitle = page.locator('.sync-control h3');
    await expect(languageSelect).toBeVisible();

    await languageSelect.selectOption('en');
    await expect(page.getByRole('button', { name: 'Cross-Session Analytics' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Session Detail' })).toBeVisible();
    await expect(syncPanelTitle).toHaveText('DB Sync');

    await languageSelect.selectOption('zh-CN');

    await expect(page.getByRole('button', { name: '跨会话分析' })).toBeVisible();
    await expect(page.getByRole('button', { name: '会话详情' })).toBeVisible();
    await expect(syncPanelTitle).toHaveText('数据库同步');
    await expect(page.locator('.date-picker-toggle')).toContainText('日期范围');
    await expect(page.locator('.session-table thead')).toContainText('项目');

    await page.reload();
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });

    await expect(page.locator('#language-mode-select')).toHaveValue('zh-CN');
    await expect(page.getByRole('button', { name: '跨会话分析' })).toBeVisible();
    await expect(syncPanelTitle).toHaveText('数据库同步');
  });
});

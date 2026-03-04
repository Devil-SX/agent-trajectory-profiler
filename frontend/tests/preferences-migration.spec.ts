import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const LEGACY_KEYS = {
  locale: 'agent-vis:locale',
  theme: 'agent-vis:theme-mode',
  density: 'agent-vis:density-mode',
  viewMode: 'agent-vis:session-browser:view-mode',
  aggregationMode: 'agent-vis:session-browser:aggregation-mode',
} as const;

test.describe('@smoke frontend preferences migration', () => {
  test('migrates legacy localStorage prefs to backend state and keeps them after reload', async ({ page }) => {
    await page.addInitScript((keys) => {
      window.localStorage.setItem(keys.locale, 'zh-CN');
      window.localStorage.setItem(keys.theme, 'dark');
      window.localStorage.setItem(keys.density, 'compact');
      window.localStorage.setItem(keys.viewMode, 'cards');
      window.localStorage.setItem(keys.aggregationMode, 'physical');
    }, LEGACY_KEYS);

    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });

    await expect(page.locator('#language-mode-select')).toHaveValue('zh-CN');
    await expect(page.locator('#theme-mode-select')).toHaveValue('dark');
    await expect(page.locator('#density-mode-select')).toHaveValue('compact');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
    await expect(page.locator('.session-table')).toBeVisible();
    await expect(page.getByRole('button', { name: '卡片视图' })).toHaveCount(0);

    const aggregationToggle = page.locator('.session-view-toggle').first();
    await expect(aggregationToggle.locator('button[aria-pressed="true"]').first()).toContainText('物理会话');

    const legacyAfterMigration = await page.evaluate((keys) => ({
      locale: window.localStorage.getItem(keys.locale),
      theme: window.localStorage.getItem(keys.theme),
      density: window.localStorage.getItem(keys.density),
      viewMode: window.localStorage.getItem(keys.viewMode),
      aggregationMode: window.localStorage.getItem(keys.aggregationMode),
    }), LEGACY_KEYS);

    expect(legacyAfterMigration.locale).toBeNull();
    expect(legacyAfterMigration.theme).toBeNull();
    expect(legacyAfterMigration.density).toBeNull();
    expect(legacyAfterMigration.viewMode).toBeNull();
    expect(legacyAfterMigration.aggregationMode).toBeNull();

    await page.reload();
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });

    await expect(page.locator('#language-mode-select')).toHaveValue('zh-CN');
    await expect(page.locator('#theme-mode-select')).toHaveValue('dark');
    await expect(page.locator('#density-mode-select')).toHaveValue('compact');
    await expect(page.locator('.session-table')).toBeVisible();
    await expect(page.getByRole('button', { name: '卡片视图' })).toHaveCount(0);
    await expect(aggregationToggle.locator('button[aria-pressed="true"]').first()).toContainText('物理会话');
  });
});

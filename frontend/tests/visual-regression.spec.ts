import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';

async function openWithTheme(page: Parameters<typeof setupMockApi>[0], mode: 'light' | 'dark') {
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
    { key: THEME_MODE_STORAGE_KEY, value: mode }
  );
  await setupMockApi(page);
  await page.goto('/');
  await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
  await expect(page.locator('html')).toHaveAttribute('data-theme', mode);
}

test.describe('Theme visual baselines', () => {
  test.use({ viewport: { width: 1280, height: 860 } });

  test('@visual light theme session browser baseline', async ({ page }) => {
    await openWithTheme(page, 'light');

    await expect(page.locator('.session-browser')).toHaveScreenshot('theme-light-session-browser.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.015,
    });
  });

  test('@visual dark theme statistics baseline', async ({ page }) => {
    await openWithTheme(page, 'dark');

    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    await expect(page.locator('.statistics-dashboard')).toHaveScreenshot('theme-dark-statistics-dashboard.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
  });
});

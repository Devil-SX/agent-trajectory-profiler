import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';
const DENSITY_MODE_STORAGE_KEY = 'agent-vis:density-mode';

async function openWithTheme(
  page: Parameters<typeof setupMockApi>[0],
  mode: 'light' | 'dark',
  density: 'comfortable' | 'compact' = 'comfortable'
) {
  await page.addInitScript(
    ({ themeKey, themeValue, densityKey, densityValue }) => {
      window.localStorage.setItem(themeKey, themeValue);
      window.localStorage.setItem(densityKey, densityValue);
    },
    {
      themeKey: THEME_MODE_STORAGE_KEY,
      themeValue: mode,
      densityKey: DENSITY_MODE_STORAGE_KEY,
      densityValue: density,
    }
  );
  await setupMockApi(page);
  await page.goto('/');
  await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
  await expect(page.locator('html')).toHaveAttribute('data-theme', mode);
  await expect(page.locator('html')).toHaveAttribute('data-density', density);
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

    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });
    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    await expect(page.locator('.statistics-dashboard')).toHaveScreenshot('theme-dark-statistics-dashboard.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.02,
    });
  });

  test('@visual dark theme session table tags baseline', async ({ page }) => {
    await openWithTheme(page, 'dark');

    await expect(page.locator('.session-browser')).toHaveScreenshot('theme-dark-session-browser.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.015,
    });
  });

  test('@visual source ecosystem comparison baseline', async ({ page }) => {
    await openWithTheme(page, 'light');

    const sourceCard = page.locator('.overview-card:has-text("Source comparison table")');
    await expect(sourceCard).toHaveScreenshot('source-comparison-table.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.015,
    });
  });

  test('@visual compact density session browser baseline', async ({ page }) => {
    await openWithTheme(page, 'light', 'compact');

    await expect(page.locator('.session-browser')).toHaveScreenshot('density-compact-session-browser.png', {
      animations: 'disabled',
      caret: 'hide',
      scale: 'css',
      maxDiffPixelRatio: 0.015,
    });
  });
});

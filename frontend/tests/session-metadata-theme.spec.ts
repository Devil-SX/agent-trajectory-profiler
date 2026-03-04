import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';

async function openTimelineWithTheme(
  page: Page,
  themeMode: 'system' | 'light' | 'dark',
  colorScheme: 'light' | 'dark'
) {
  await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' });
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
    { key: THEME_MODE_STORAGE_KEY, value: themeMode }
  );

  await setupMockApi(page);
  await page.goto('/');
  await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });
  await page.locator('.session-table tbody tr[data-session-id]').first().click();
  await page.waitForSelector('.metadata-sidebar .sidebar-title', { timeout: 5000 });
}

async function expectSidebarBackground(page: Page, expectedColor: string) {
  const sidebar = page.locator('.metadata-sidebar').first();
  await expect
    .poll(
      async () =>
        sidebar.evaluate((element) => {
          const htmlElement = element as HTMLElement;
          return window.getComputedStyle(htmlElement).backgroundColor;
        }),
      { timeout: 5000 }
    )
    .toBe(expectedColor);
}

test.describe('Session metadata sidebar theme behavior', () => {
  test('@smoke sidebar follows selected light/dark mode even when system is dark', async ({ page }) => {
    await openTimelineWithTheme(page, 'light', 'dark');

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expectSidebarBackground(page, 'rgb(255, 255, 255)');

    await page.selectOption('#theme-mode-select', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expectSidebarBackground(page, 'rgb(26, 26, 26)');
  });

  test('@a11y sidebar tracks system theme changes and stays consistent in mobile drawer', async ({ page }) => {
    await openTimelineWithTheme(page, 'system', 'dark');

    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expectSidebarBackground(page, 'rgb(26, 26, 26)');

    await page.emulateMedia({ colorScheme: 'light', reducedMotion: 'reduce' });
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await expectSidebarBackground(page, 'rgb(255, 255, 255)');

    await page.setViewportSize({ width: 390, height: 844 });
    const mobileSidebarToggle = page.locator('.mobile-sidebar-toggle');
    await expect(mobileSidebarToggle).toBeVisible();
    await mobileSidebarToggle.click();

    const mobileSidebar = page.locator('.sidebar-container.mobile-open .metadata-sidebar').first();
    await expect(mobileSidebar).toBeVisible();

    await expect
      .poll(
        async () =>
          mobileSidebar.evaluate((element) => {
            const htmlElement = element as HTMLElement;
            return window.getComputedStyle(htmlElement).backgroundColor;
          }),
        { timeout: 5000 }
      )
      .toBe('rgb(255, 255, 255)');

    await page.selectOption('#theme-mode-select', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');

    await expect
      .poll(
        async () =>
          mobileSidebar.evaluate((element) => {
            const htmlElement = element as HTMLElement;
            return window.getComputedStyle(htmlElement).backgroundColor;
          }),
        { timeout: 5000 }
      )
      .toBe('rgb(26, 26, 26)');
  });
});

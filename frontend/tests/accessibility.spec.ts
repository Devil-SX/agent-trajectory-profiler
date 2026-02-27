import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const THEME_MODE_STORAGE_KEY = 'agent-vis:theme-mode';

async function openWithTheme(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript(
    ({ key, value }) => {
      window.localStorage.setItem(key, value);
    },
    { key: THEME_MODE_STORAGE_KEY, value: theme }
  );

  await setupMockApi(page);
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
}

async function readContrastRatio(page: Page, selector: string): Promise<number> {
  const ratio = await page.evaluate((targetSelector) => {
    const parseColor = (value: string) => {
      const match = value.match(/rgba?\(([^)]+)\)/i);
      if (!match) return null;

      const parts = match[1].split(',').map((part) => Number.parseFloat(part.trim()));
      if (parts.length < 3 || parts.some((part) => Number.isNaN(part))) {
        return null;
      }

      return {
        r: parts[0],
        g: parts[1],
        b: parts[2],
        a: parts.length >= 4 && !Number.isNaN(parts[3]) ? parts[3] : 1,
      };
    };

    const toLinear = (channel: number) => {
      const normalized = channel / 255;
      return normalized <= 0.03928
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4;
    };

    const luminance = (color: { r: number; g: number; b: number }) => (
      0.2126 * toLinear(color.r) +
      0.7152 * toLinear(color.g) +
      0.0722 * toLinear(color.b)
    );

    const target = document.querySelector(targetSelector) as HTMLElement | null;
    if (!target) return null;

    const foreground = parseColor(window.getComputedStyle(target).color);
    if (!foreground) return null;

    let background: { r: number; g: number; b: number; a: number } | null = null;
    let current: HTMLElement | null = target;

    while (current && !background) {
      const parsed = parseColor(window.getComputedStyle(current).backgroundColor);
      if (parsed && parsed.a > 0) {
        background = parsed;
        break;
      }
      current = current.parentElement;
    }

    if (!background) {
      return null;
    }

    const l1 = luminance(foreground);
    const l2 = luminance(background);
    const brighter = Math.max(l1, l2);
    const darker = Math.min(l1, l2);

    return (brighter + 0.05) / (darker + 0.05);
  }, selector);

  expect(ratio).not.toBeNull();
  return ratio as number;
}

test.describe('Accessibility contracts', () => {
  test('@a11y keyboard focus remains visible on interactive controls', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });

    await page.keyboard.press('Tab');

    const boxShadow = await page.evaluate(() => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return 'none';
      return window.getComputedStyle(active).boxShadow;
    });

    expect(boxShadow).not.toBe('none');

    const crossSessionTab = page.getByRole('button', { name: 'Cross-Session Analytics' });
    await crossSessionTab.focus();
    await page.keyboard.press('Enter');
    await expect(crossSessionTab).toHaveClass(/active/);
  });

  test('@a11y statistics text contrast passes in light and dark themes', async ({ page }) => {
    await openWithTheme(page, 'light');
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    const lightTitleContrast = await readContrastRatio(page, '.dashboard-title');
    const lightNoteContrast = await readContrastRatio(page, '.section-header p');
    expect(lightTitleContrast).toBeGreaterThanOrEqual(4.5);
    expect(lightNoteContrast).toBeGreaterThanOrEqual(4.5);

    await page.selectOption('#theme-mode-select', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    const darkTitleContrast = await readContrastRatio(page, '.dashboard-title');
    const darkNoteContrast = await readContrastRatio(page, '.section-header p');
    expect(darkTitleContrast).toBeGreaterThanOrEqual(4.5);
    expect(darkNoteContrast).toBeGreaterThanOrEqual(4.5);
  });
});

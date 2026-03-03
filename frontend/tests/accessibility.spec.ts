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

function buildAnomalySessionDetail(sessionId: string) {
  const messages = [
    {
      sessionId,
      uuid: `${sessionId}-msg-1`,
      timestamp: '2024-02-01T10:00:00Z',
      type: 'user',
      message: {
        role: 'user',
        content: 'Trigger anomaly markers for accessibility checks.',
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-2`,
      timestamp: '2024-02-01T10:01:00Z',
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: `tool-${sessionId}-1`,
            name: 'Bash',
            input: { command: 'false' },
          },
          {
            type: 'tool_result',
            tool_use_id: `tool-${sessionId}-1`,
            content: 'Command failed',
            is_error: true,
          },
          {
            type: 'text',
            text: 'Tool execution failed. I will retry.',
          },
        ],
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-3`,
      timestamp: '2024-02-01T10:02:00Z',
      type: 'user',
      message: {
        role: 'user',
        content: 'Please continue.',
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-4`,
      timestamp: '2024-02-01T10:14:30Z',
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          {
            type: 'text',
            text: 'Recovered after delay.',
          },
        ],
      },
    },
  ];

  return {
    session: {
      metadata: {
        session_id: sessionId,
        project_path: '/home/user/project',
        git_branch: 'main',
        version: '1.0.0',
        created_at: '2024-02-01T10:00:00Z',
        updated_at: '2024-02-01T10:14:30Z',
        total_messages: messages.length,
        total_tokens: 2400,
      },
      messages,
    },
  };
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
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });
    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    const lightTitleContrast = await readContrastRatio(page, '.dashboard-title');
    const lightNoteContrast = await readContrastRatio(page, '.section-header p');
    expect(lightTitleContrast).toBeGreaterThanOrEqual(4.5);
    expect(lightNoteContrast).toBeGreaterThanOrEqual(4.5);

    await page.selectOption('#theme-mode-select', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });
    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    const darkTitleContrast = await readContrastRatio(page, '.dashboard-title');
    const darkNoteContrast = await readContrastRatio(page, '.section-header p');
    expect(darkTitleContrast).toBeGreaterThanOrEqual(4.5);
    expect(darkNoteContrast).toBeGreaterThanOrEqual(4.5);
  });

  test('@a11y session table tags keep contrast and support keyboard row selection', async ({ page }) => {
    await openWithTheme(page, 'light');
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });

    const lightEcosystemContrast = await readContrastRatio(page, '.session-tag--ecosystem-claude');
    const lightBottleneckContrast = await readContrastRatio(page, '.session-tag--bottleneck-model');
    const lightAutomationContrast = await readContrastRatio(page, '.session-tag--automation-medium');
    expect(lightEcosystemContrast).toBeGreaterThanOrEqual(4.5);
    expect(lightBottleneckContrast).toBeGreaterThanOrEqual(4.5);
    expect(lightAutomationContrast).toBeGreaterThanOrEqual(4.5);

    const firstRow = page.locator('.session-table tbody tr[data-session-id]').first();
    await firstRow.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await expect(page.locator('.session-table')).toBeVisible();

    await page.selectOption('#theme-mode-select', 'dark');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    const darkEcosystemContrast = await readContrastRatio(page, '.session-tag--ecosystem-claude');
    const darkBottleneckContrast = await readContrastRatio(page, '.session-tag--bottleneck-model');
    const darkAutomationContrast = await readContrastRatio(page, '.session-tag--automation-medium');
    expect(darkEcosystemContrast).toBeGreaterThanOrEqual(4.5);
    expect(darkBottleneckContrast).toBeGreaterThanOrEqual(4.5);
    expect(darkAutomationContrast).toBeGreaterThanOrEqual(4.5);
  });

  test('@a11y density mode toggle is keyboard-accessible and keeps table navigation usable', async ({
    page,
  }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });

    const densitySelect = page.locator('#density-mode-select');
    await densitySelect.focus();
    await expect(densitySelect).toBeFocused();
    await densitySelect.selectOption('compact');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');

    const firstRow = page.locator('.session-table tbody tr[data-session-id]').first();
    await firstRow.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByRole('button', { name: 'Session Detail' })).toHaveClass(/active/);
  });

  test('@a11y minimap anomaly markers expose keyboard focus and labels', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute('**/api/sessions/test-session-001');
    await page.route('**/api/sessions/test-session-001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildAnomalySessionDetail('test-session-001')),
      });
    });

    await page.goto('/');
    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 5000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-panel"]', { timeout: 10000 });

    const marker = page.locator('[data-testid="timeline-anomaly-tool_error"]').first();
    await expect(marker).toBeVisible();
    await expect(marker).toHaveAttribute('aria-label', /Anomaly marker at/);

    await marker.focus();
    await expect(marker).toBeFocused();

    const messageScroll = page.locator('[data-testid="timeline-message-scroll"]');
    await messageScroll.evaluate((node) => {
      const element = node as HTMLElement;
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event('scroll'));
    });
    const beforeJump = await messageScroll.evaluate((node) => (node as HTMLElement).scrollTop);

    await marker.press('Enter');

    await expect
      .poll(
        async () => messageScroll.evaluate((node) => (node as HTMLElement).scrollTop),
        { timeout: 3000 }
      )
      .toBeLessThan(beforeJump - 20);
  });
});

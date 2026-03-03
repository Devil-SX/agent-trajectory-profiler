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

function buildAnomalySessionDetail(sessionId: string) {
  const messages = [
    {
      sessionId,
      uuid: `${sessionId}-msg-1`,
      timestamp: '2024-02-01T10:00:00Z',
      type: 'user',
      message: {
        role: 'user',
        content: 'Generate minimap anomaly markers.',
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
            text: 'Tool failed.',
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
        content: 'Retry now.',
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
            text: 'Recovered after model stall.',
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
        total_tokens: 1800,
      },
      messages,
    },
  };
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

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 5000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
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

  test('@visual minimap anomaly line-marker baseline', async ({ page }) => {
    await openWithTheme(page, 'light');

    await page.unroute('**/api/sessions/test-session-001');
    await page.route('**/api/sessions/test-session-001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildAnomalySessionDetail('test-session-001')),
      });
    });

    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 5000 });
    await page.locator('.session-table tbody tr[data-session-id]').first().click();
    await page.waitForSelector('[data-testid="timeline-minimap-panel"]', { timeout: 10000 });

    await expect(page.locator('[data-testid="timeline-minimap-panel"]')).toHaveScreenshot(
      'timeline-minimap-anomaly-markers.png',
      {
        animations: 'disabled',
        caret: 'hide',
        scale: 'css',
        maxDiffPixelRatio: 0.02,
      }
    );
  });
});

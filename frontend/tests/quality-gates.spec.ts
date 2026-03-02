import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';
import { mockSessionDetail } from './fixtures/mockData';

function buildLongTimelineMessages(total: number): Array<Record<string, unknown>> {
  const messages: Array<Record<string, unknown>> = [];

  for (let i = 0; i < total; i++) {
    const isUser = i % 2 === 0;
    const uuid = `long-msg-${i.toString().padStart(3, '0')}`;
    const minutes = i.toString().padStart(2, '0');
    const timestamp = `2024-02-01T10:${minutes}:00Z`;

    messages.push({
      sessionId: 'test-session-001',
      uuid,
      timestamp,
      type: isUser ? 'user' : 'assistant',
      message: isUser
        ? {
            role: 'user',
            content: `User message ${i}`,
          }
        : {
            role: 'assistant',
            content: [
              {
                type: 'text',
                text: `Assistant response ${i}`,
              },
            ],
          },
    });
  }

  return messages;
}

async function setupLongTimelineMock(page: Page) {
  await setupMockApi(page);

  const longDetail = {
    ...mockSessionDetail,
    session: {
      ...mockSessionDetail.session,
      messages: buildLongTimelineMessages(120),
    },
  };

  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(longDetail),
    });
  });
}

test.describe('Quality Gates', () => {
  test('@smoke loads default session and timeline', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await expect(page.locator('.message-timeline')).toBeVisible();
    await expect(page.locator('button.tab-button.active')).toContainText('Timeline');
  });

  test('@smoke date picker dropdown remains fully inside viewport', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });

    await page.click('.date-picker-toggle');
    const dropdown = page.locator('.date-picker-dropdown');
    await expect(dropdown).toBeVisible();

    const viewport = page.viewportSize();
    const box = await dropdown.boundingBox();

    expect(viewport).not.toBeNull();
    expect(box).not.toBeNull();

    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.y).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(viewport!.width + 1);
    expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height + 1);
  });

  test('@smoke timeline does not auto-scroll to the bottom on initial load', async ({ page }) => {
    await setupLongTimelineMock(page);
    await page.goto('/');
    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(250);

    const metrics = await page.evaluate(() => {
      return {
        scrollY: window.scrollY,
        scrollHeight: document.documentElement.scrollHeight,
        viewportHeight: window.innerHeight,
      };
    });

    expect(metrics.scrollHeight).toBeGreaterThan(metrics.viewportHeight + 200);
    expect(metrics.scrollY).toBeLessThanOrEqual(5);
  });

  test('@smoke statistics view provides a valid vertical scrolling path', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });

    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });

    const overflowMode = await page.locator('.session-content--scrollable').evaluate((element) => {
      return window.getComputedStyle(element).overflowY;
    });
    expect(['auto', 'scroll']).toContain(overflowMode);

    const hasScrollPath = await page.evaluate(() => {
      const panel = document.querySelector('.session-content--scrollable') as HTMLElement | null;
      const dashboard = document.querySelector('.statistics-dashboard') as HTMLElement | null;
      const doc = document.scrollingElement;

      const panelScrollable = panel ? panel.scrollHeight > panel.clientHeight : false;
      const dashboardScrollable = dashboard ? dashboard.scrollHeight > dashboard.clientHeight : false;
      const docScrollable = doc ? doc.scrollHeight > doc.clientHeight : false;

      return panelScrollable || dashboardScrollable || docScrollable;
    });

    expect(hasScrollPath).toBeTruthy();
  });

  test('@full tab switch and session switch do not emit console errors', async ({ page }) => {
    const errors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') {
        errors.push(message.text());
      }
    });

    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });

    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });
    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForSelector('.advanced-analytics', { timeout: 5000 });

    await page.locator('.session-card').nth(1).click();
    await page.waitForTimeout(500);
    await expect(page.locator('.session-card').nth(1)).toHaveClass(/session-card--selected/);

    expect(errors).toEqual([]);
  });

  test('@full date filter state persists and can be cleared safely', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });

    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });
    await page.click('button:has-text("Last 7 days")');
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();

    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });
    await expect(page.locator('.date-input').first()).not.toHaveValue('');
    await expect(page.locator('.date-input').nth(1)).not.toHaveValue('');

    await page.click('.picker-action-button--clear');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
    await expect(page.locator('.date-picker-toggle--filtered')).not.toBeVisible();
  });

  test('@full active tab state persists when switching sessions', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });

    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForSelector('.advanced-analytics', { timeout: 5000 });

    await page.locator('.session-card').nth(1).click();
    await page.waitForTimeout(600);

    await expect(page.locator('.session-card').nth(1)).toHaveClass(/session-card--selected/);
    await expect(page.locator('button.tab-button.active')).toContainText('Advanced Analytics');
  });
});

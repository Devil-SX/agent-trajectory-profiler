import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';
import { mockSessionDetail, mockSessionList, mockSessionStatistics } from './fixtures/mockData';

function buildSecondSessionDetail() {
  return {
    session: {
      ...mockSessionDetail.session,
      metadata: {
        ...mockSessionDetail.session.metadata,
        session_id: 'test-session-002',
      },
      messages: [
        {
          sessionId: 'test-session-002',
          uuid: 'switch-msg-001',
          timestamp: '2024-02-02T14:00:00Z',
          type: 'user',
          message: {
            role: 'user',
            content: 'Second session unique marker request.',
          },
        },
        {
          sessionId: 'test-session-002',
          uuid: 'switch-msg-002',
          timestamp: '2024-02-02T14:01:00Z',
          type: 'assistant',
          message: {
            role: 'assistant',
            content: 'Second session unique marker response.',
            usage: {
              input_tokens: 80,
              output_tokens: 44,
            },
          },
        },
      ],
    },
  };
}

function buildSecondSessionStatistics() {
  return {
    ...mockSessionStatistics,
    session_id: 'test-session-002',
  };
}

test.describe('Session loading UX', () => {
  test('@smoke initial session load shows skeleton indicator then resolves to list', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute(/\/api\/sessions(?:\?.*)?$/);
    await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 900));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessionList),
      });
    });

    await page.goto('/');
    await expect(page.locator('.loading-container[role="status"]')).toBeVisible();
    await expect(page.locator('.session-loading-skeleton .session-skeleton-row')).toHaveCount(6);
    await expect(page.locator('.loading-container')).toContainText('Loading sessions');

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
    await expect(page.locator('.session-loading-skeleton')).toHaveCount(0);
    await expect(page.locator('.session-table tbody tr[data-session-id]')).toHaveCount(2);
  });

  test('@full loading failure state exposes retry and recovers', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute(/\/api\/sessions(?:\?.*)?$/);

    let allowSuccess = false;
    await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
      if (!allowSuccess) {
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'temporary outage' }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockSessionList),
      });
    });

    await page.goto('/');
    await expect(page.locator('.session-browser.error')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.session-retry-button')).toBeVisible();
    allowSuccess = true;
    await page.locator('.session-retry-button').click();

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
    await expect(page.locator('.session-table tbody tr[data-session-id]')).toHaveCount(2);
  });

  test('@full switching sessions keeps panel-level loading state without blank flash', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute('**/api/sessions/test-session-002');
    await page.unroute('**/api/sessions/test-session-002/statistics');

    await page.route('**/api/sessions/test-session-002', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSecondSessionDetail()),
      });
    });

    await page.route('**/api/sessions/test-session-002/statistics', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(buildSecondSessionStatistics()),
      });
    });

    await page.goto('/');
    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });
    await expect(page.getByText('Hello, can you help me with a bug?')).toBeVisible();

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await page.waitForSelector('tr[data-session-id="test-session-002"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-002"]').click();

    await expect(page.locator('.detail-toolbar')).toBeVisible();
    await expect(page.locator('.message-timeline.loading')).toBeVisible();
    await expect(page.locator('.timeline-loading-skeleton .timeline-loading-skeleton-row')).toHaveCount(6);
    await expect(page.locator('.no-session')).toHaveCount(0);

    await expect(page.getByText('Second session unique marker response.')).toBeVisible({ timeout: 10000 });
    await expect(page.locator('.message-timeline.loading')).toHaveCount(0);
  });

  test('@a11y loading status is announced and keyboard flow remains valid after resolve', async ({ page }) => {
    await setupMockApi(page);
    await page.unroute(/\/api\/sessions(?:\?.*)?$/);
    await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 900));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            {
              session_id: 'test-session-001',
              ecosystem: 'claude_code',
              project_path: '/home/user/project',
              created_at: '2024-02-01T10:00:00Z',
              updated_at: '2024-02-01T11:30:00Z',
              total_messages: 25,
              total_tokens: 15000,
              git_branch: 'main',
              version: '1.0.0',
              parsed_at: null,
              duration_seconds: 5400,
              bottleneck: 'Model',
              automation_ratio: 2.8,
            },
          ],
          count: 1,
          page: 1,
          page_size: 200,
          total_pages: 1,
        }),
      });
    });

    await page.goto('/');
    const liveRegion = page.locator('.loading-container[role="status"]');
    await expect(liveRegion).toBeVisible();
    await expect(liveRegion).toHaveAttribute('aria-live', 'polite');

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });
    await page.keyboard.press('Tab');
    const hasKeyboardFocus = await page.evaluate(() => {
      const active = document.activeElement;
      return Boolean(active && active !== document.body);
    });
    expect(hasKeyboardFocus).toBeTruthy();
  });
});

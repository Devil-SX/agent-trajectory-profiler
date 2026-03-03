import { expect, test } from '@playwright/test';
import {
  codexParitySessionDetail,
  codexParitySessionId,
  codexParitySessionList,
  codexParitySessionStatistics,
} from './fixtures/codexParityData';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke Codex parity pipeline', () => {
  test('@smoke codex golden fixture remains visible across timeline rendering', async ({ page, isMobile }) => {
    await setupMockApi(page);

    await page.unroute(/\/api\/sessions(?:\?.*)?$/);
    await page.unroute(`**/api/sessions/${codexParitySessionId}`);
    await page.unroute(`**/api/sessions/${codexParitySessionId}/statistics`);

    await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(codexParitySessionList),
      });
    });

    await page.route(`**/api/sessions/${codexParitySessionId}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(codexParitySessionDetail),
      });
    });

    await page.route(`**/api/sessions/${codexParitySessionId}/statistics`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(codexParitySessionStatistics),
      });
    });

    await page.goto('/');
    await page.waitForSelector(`tr[data-session-id="${codexParitySessionId}"]`, { timeout: 10000 });
    await page.locator(`tr[data-session-id="${codexParitySessionId}"]`).click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });

    await expect(page.locator('.message-count')).toContainText('4 visible messages');
    await expect(page.locator('.message-count')).toContainText('7 raw messages');
    await expect(page.locator('.message-count')).toContainText('2 technical events hidden');
    await expect(page.locator('.message-count')).toContainText('1 linked tool-result message folded');
    await expect(page.getByText('(Empty content)')).toHaveCount(0);
    await expect(page.locator('.tool-call-block')).toHaveCount(1);
    await expect(page.getByText('token_count')).toHaveCount(0);
    await expect(page.getByText('session_meta source=cli')).toHaveCount(0);

    await page.locator('.result-toggle-button').first().click();
    await expect(page.getByText("print('ok')")).toBeVisible();

    if (!isMobile) {
      await page.getByTestId('timeline-toggle-technical-events').check();
      await expect(page.locator('.message-count')).toContainText('6 visible messages');
      await expect(page.locator('.message-count')).toContainText('7 raw messages');
      await expect(page.getByText('token_count')).toBeVisible();
      await expect(page.getByText('session_meta source=cli')).toBeVisible();
    }
    await expect(page.getByText('Run parity check on parser and timeline.')).toHaveCount(1);
  });
});

import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

function buildLongSessionDetail(sessionId: string) {
  const start = new Date('2024-02-01T10:00:00Z').getTime();
  const messages = Array.from({ length: 180 }, (_, index) => {
    const timestamp = new Date(start + index * 60_000).toISOString();
    const isUser = index % 2 === 0;
    return {
      sessionId,
      uuid: `${sessionId}-msg-${index + 1}`,
      timestamp,
      type: isUser ? 'user' : 'assistant',
      message: isUser
        ? {
            role: 'user',
            content: `User message ${index + 1}: scroll behavior validation payload.`,
          }
        : {
            role: 'assistant',
            content: [
              {
                type: 'text',
                text: `Assistant response ${index + 1}: ${'long output '.repeat(12)}`,
              },
            ],
            usage: {
              input_tokens: 120,
              output_tokens: 80,
            },
          },
    };
  });

  return {
    session: {
      metadata: {
        session_id: sessionId,
        project_path: '/home/user/project',
        git_branch: 'main',
        version: '1.0.0',
        created_at: '2024-02-01T10:00:00Z',
        updated_at: '2024-02-01T13:00:00Z',
        total_messages: messages.length,
        total_tokens: 45000,
      },
      messages,
    },
  };
}

async function setupLongTimelineMocks(page: Page) {
  await setupMockApi(page);

  const longSessionOne = buildLongSessionDetail('test-session-001');
  const longSessionTwo = buildLongSessionDetail('test-session-002');

  await page.unroute('**/api/sessions/test-session-001');
  await page.unroute('**/api/sessions/test-session-002');

  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(longSessionOne),
    });
  });

  await page.route('**/api/sessions/test-session-002', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(longSessionTwo),
    });
  });
}

async function getWindowScrollY(page: Page) {
  return page.evaluate(() => window.scrollY);
}

test.describe('@smoke Timeline scroll behavior', () => {
  test('enters session detail at top and only scrolls to bottom on explicit user action', async ({
    page,
  }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });

    const initialScrollY = await getWindowScrollY(page);
    expect(initialScrollY).toBeLessThan(40);

    await expect(page.locator('.timeline-jump-button')).toBeVisible();
    await page.locator('.timeline-jump-button').click();
    await page.waitForTimeout(250);

    const afterJumpScrollY = await getWindowScrollY(page);
    expect(afterJumpScrollY).toBeLessThan(80);
  });

  test('switching sessions does not unexpectedly jump to timeline bottom', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await page.waitForSelector('tr[data-session-id="test-session-002"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-002"]').click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });

    const secondSessionScrollY = await getWindowScrollY(page);
    expect(secondSessionScrollY).toBeLessThan(40);
  });
});

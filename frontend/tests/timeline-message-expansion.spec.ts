import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

const SESSION_ID = 'test-session-001';
const ASSISTANT_TAIL_MARKER = 'ASSISTANT_EXPANSION_TAIL_MARKER';
const USER_TAIL_MARKER = 'USER_EXPANSION_TAIL_MARKER';

function buildLongText(label: string, tailMarker: string): string {
  const lines = Array.from({ length: 32 }, (_, index) => (
    `${label} long line ${index + 1}: ${'dense timeline content '.repeat(10)}`
  ));
  lines.push(tailMarker);
  return lines.join('\n');
}

function buildLongContentSessionDetail(sessionId: string) {
  const assistantLongText = buildLongText('Assistant', ASSISTANT_TAIL_MARKER);
  const userLongText = buildLongText('User', USER_TAIL_MARKER);

  const messages = [
    {
      sessionId,
      uuid: `${sessionId}-msg-1`,
      timestamp: '2024-02-01T10:00:00Z',
      type: 'user',
      message: {
        role: 'user',
        content: 'Short user message.',
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
            type: 'text',
            text: assistantLongText,
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
        content: userLongText,
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-4`,
      timestamp: '2024-02-01T10:03:00Z',
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          {
            type: 'text',
            text: 'Short assistant follow-up.',
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
        updated_at: '2024-02-01T10:03:00Z',
        total_messages: messages.length,
        total_tokens: 9500,
      },
      messages,
    },
  };
}

async function setupLongContentTimelineMock(page: Page) {
  await setupMockApi(page);
  await page.unroute('**/api/sessions/test-session-001');
  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildLongContentSessionDetail(SESSION_ID)),
    });
  });
}

async function openSessionTimeline(page: Page) {
  await page.goto('/');
  await page.waitForSelector(`tr[data-session-id="${SESSION_ID}"]`, { timeout: 10000 });
  await page.locator(`tr[data-session-id="${SESSION_ID}"]`).click();
  await page.waitForSelector('[data-testid="message-timeline"]', { timeout: 10000 });
}

test.describe('Timeline long message expansion', () => {
  test('@smoke truncates long messages by default and exposes expand action', async ({ page }) => {
    await setupLongContentTimelineMock(page);
    await openSessionTimeline(page);

    await expect(page.locator('.message-expand-button')).toHaveCount(2);
    await expect(page.locator(`[data-testid="timeline-expand-${SESSION_ID}-msg-2"]`)).toBeVisible();
    await expect(page.locator('.messages-container')).not.toContainText(ASSISTANT_TAIL_MARKER);

    await page.locator(`[data-testid="timeline-expand-${SESSION_ID}-msg-2"]`).click();
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toBeVisible();
    await expect(page.locator('[data-testid="timeline-message-modal-content"]')).toContainText(
      ASSISTANT_TAIL_MARKER
    );
  });

  test('@full expanded message modal preserves full content and supports all close paths', async ({ page }) => {
    await setupLongContentTimelineMock(page);
    await openSessionTimeline(page);

    const assistantExpandButton = page.locator(`[data-testid="timeline-expand-${SESSION_ID}-msg-2"]`);
    await assistantExpandButton.click();
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toBeVisible();
    await expect(page.locator('[data-testid="timeline-message-modal-content"]')).toContainText(
      ASSISTANT_TAIL_MARKER
    );

    await page.locator('[data-testid="timeline-message-modal-overlay"]').click({ position: { x: 6, y: 6 } });
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toHaveCount(0);

    await assistantExpandButton.click();
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toBeVisible();
    await page.locator('.timeline-message-modal-close').click();
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toHaveCount(0);

    await assistantExpandButton.click();
    await expect(page.locator('[data-testid="timeline-message-modal-content"]')).toContainText(
      ASSISTANT_TAIL_MARKER
    );
    await page.keyboard.press('Escape');
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toHaveCount(0);
  });

  test('@a11y expand flow supports keyboard activation, ESC close, and focus return', async ({ page }) => {
    await setupLongContentTimelineMock(page);
    await openSessionTimeline(page);

    const userExpandButton = page.locator(`[data-testid="timeline-expand-${SESSION_ID}-msg-3"]`);
    await userExpandButton.focus();
    await expect(userExpandButton).toBeFocused();

    await userExpandButton.press('Enter');
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toBeVisible();
    await expect(page.locator('.timeline-message-modal-close')).toBeFocused();
    await expect(page.locator('[data-testid="timeline-message-modal-content"]')).toContainText(
      USER_TAIL_MARKER
    );

    await page.keyboard.press('Escape');
    await expect(page.locator('[data-testid="timeline-message-modal"]')).toHaveCount(0);
    await expect(userExpandButton).toBeFocused();
  });
});

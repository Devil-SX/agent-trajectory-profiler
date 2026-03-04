import { expect, test, type Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

function buildLongSessionDetail(sessionId: string) {
  let current = new Date('2024-02-01T10:00:00Z').getTime();
  const messages = Array.from({ length: 180 }, (_, index) => {
    const isUser = index % 2 === 0;
    if (index > 0) {
      const isStallTransition = !isUser && index % 48 === 1;
      current += isStallTransition ? 12 * 60_000 : 60_000;
    }
    const timestamp = new Date(current).toISOString();
    const includeToolError = !isUser && index % 36 === 1;
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
            content: includeToolError
              ? [
                  {
                    type: 'tool_use',
                    id: `tool-${sessionId}-${index + 1}`,
                    name: 'Bash',
                    input: { command: 'false' },
                  },
                  {
                    type: 'tool_result',
                    tool_use_id: `tool-${sessionId}-${index + 1}`,
                    content: 'Command failed with non-zero exit status',
                    is_error: true,
                  },
                  {
                    type: 'text',
                    text: `Assistant tool error response ${index + 1}: ${'long output '.repeat(10)}`,
                  },
                ]
              : [
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

function buildSplitToolChainSession(sessionId: string) {
  const messages = [
    {
      sessionId,
      uuid: `${sessionId}-msg-1`,
      timestamp: '2024-02-01T10:00:00Z',
      type: 'user',
      message: {
        role: 'user',
        content: 'Please inspect and fix the issue.',
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
            text: 'I will inspect the file now.',
          },
          {
            type: 'tool_use',
            id: `tool-${sessionId}-1`,
            name: 'Read',
            input: { file_path: '/tmp/demo.py' },
          },
        ],
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-3`,
      timestamp: '2024-02-01T10:01:08Z',
      type: 'user',
      message: {
        role: 'user',
        content: [
          {
            type: 'tool_result',
            tool_use_id: `tool-${sessionId}-1`,
            content: 'line 12: NameError: x is not defined',
            is_error: true,
          },
        ],
      },
    },
    {
      sessionId,
      uuid: `${sessionId}-msg-4`,
      timestamp: '2024-02-01T10:02:00Z',
      type: 'assistant',
      message: {
        role: 'assistant',
        content: [
          {
            type: 'text',
            text: 'I found the root cause and prepared a fix.',
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
        updated_at: '2024-02-01T10:02:00Z',
        total_messages: messages.length,
        total_tokens: 4000,
      },
      messages,
    },
  };
}

async function setupSplitToolChainMock(page: Page) {
  await setupMockApi(page);
  await page.unroute('**/api/sessions/test-session-001');
  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildSplitToolChainSession('test-session-001')),
    });
  });
}

async function getWindowScrollY(page: Page) {
  return page.evaluate(() => window.scrollY);
}

test.describe('Timeline scroll behavior', () => {
  test('@smoke codex-style split tool_result is linked and does not render empty rows', async ({
    page,
  }) => {
    await setupSplitToolChainMock(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('.message-timeline', { timeout: 10000 });

    await expect(page.getByText('(Empty content)')).toHaveCount(0);
    await expect(page.locator('.tool-call-block')).toHaveCount(1);
    await page.locator('.result-toggle-button').first().click();
    await expect(page.getByText('line 12: NameError: x is not defined')).toBeVisible();
  });

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

  test('@full minimap click jumps to a deeper timeline region', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-track"]', { timeout: 10000 });

    const beforeScrollTop = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);

    const track = page.locator('[data-testid="timeline-minimap-track"]');
    const box = await track.boundingBox();
    if (!box) {
      throw new Error('Expected minimap track to have a visible bounding box');
    }

    await track.click({
      position: {
        x: box.width / 2,
        y: box.height * 0.85,
      },
    });

    await expect
      .poll(
        async () =>
          page
            .locator('[data-testid="timeline-message-scroll"]')
            .evaluate((node) => (node as HTMLElement).scrollTop),
        { timeout: 2000 }
      )
      .toBeGreaterThan(beforeScrollTop + 120);
  });

  test('@full minimap viewport drag keeps message scroll synchronized', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-viewport"]', { timeout: 10000 });

    const viewport = page.locator('[data-testid="timeline-minimap-viewport"]');
    const viewportBox = await viewport.boundingBox();
    if (!viewportBox) {
      throw new Error('Expected minimap viewport bounding box');
    }

    const startScrollTop = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);

    await page.mouse.move(viewportBox.x + viewportBox.width / 2, viewportBox.y + viewportBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      viewportBox.x + viewportBox.width / 2,
      viewportBox.y + viewportBox.height / 2 + 120,
      { steps: 6 }
    );
    await page.mouse.up();
    await page.waitForTimeout(120);

    const endScrollTop = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);

    expect(endScrollTop).toBeGreaterThan(startScrollTop + 80);
  });

  test('@smoke minimap viewport drag does not produce blank content area', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-viewport"]', { timeout: 10000 });

    const viewport = page.locator('[data-testid="timeline-minimap-viewport"]');
    const viewportBox = await viewport.boundingBox();
    if (!viewportBox) {
      throw new Error('Expected minimap viewport bounding box');
    }

    const startScrollTop = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);

    await page.mouse.move(viewportBox.x + viewportBox.width / 2, viewportBox.y + viewportBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(
      viewportBox.x + viewportBox.width / 2,
      viewportBox.y + viewportBox.height / 2 + 220,
      { steps: 12 }
    );
    await page.mouse.up();
    await page.waitForTimeout(180);

    let endScrollTop = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);

    if (endScrollTop <= startScrollTop + 20) {
      const track = page.locator('[data-testid="timeline-minimap-track"]');
      const trackBox = await track.boundingBox();
      if (trackBox) {
        await page.mouse.click(trackBox.x + trackBox.width / 2, trackBox.y + trackBox.height * 0.9);
        await page.waitForTimeout(180);
        endScrollTop = await page
          .locator('[data-testid="timeline-message-scroll"]')
          .evaluate((node) => (node as HTMLElement).scrollTop);
      }
    }
    expect(endScrollTop).toBeGreaterThan(startScrollTop + 20);

    await expect(page.locator('.message-row')).not.toHaveCount(0);
    await expect(page.locator('.message-row .message-content').first()).toContainText(/\S+/);
  });

  test('@full minimap top/mid/bottom mapping keeps visible window aligned', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-track"]', { timeout: 10000 });

    const track = page.locator('[data-testid="timeline-minimap-track"]');
    const box = await track.boundingBox();
    if (!box) {
      throw new Error('Expected minimap track to have a visible bounding box');
    }

    const clickAtRatio = async (ratio: number) => {
      await page.mouse.click(box.x + box.width / 2, box.y + box.height * ratio);
      await page.waitForTimeout(180);
      return page
        .locator('[data-testid="timeline-message-scroll"]')
        .evaluate((node) => (node as HTMLElement).scrollTop);
    };

    // Click twice per segment to let dynamic row measurements settle before asserting.
    await clickAtRatio(0.08);
    const topScroll = await clickAtRatio(0.08);
    await clickAtRatio(0.5);
    const midScroll = await clickAtRatio(0.5);
    await clickAtRatio(0.92);
    const bottomScroll = await clickAtRatio(0.92);

    expect(topScroll).toBeGreaterThanOrEqual(0);
    expect(midScroll).toBeGreaterThan(topScroll + 80);
    expect(bottomScroll).toBeGreaterThan(topScroll + 160);
    expect(bottomScroll).toBeGreaterThanOrEqual(midScroll - 120);
    await expect(page.locator('.message-row')).not.toHaveCount(0);
    await expect(page.locator('.message-row .message-content').first()).toContainText(/\S+/);
  });

  test('@full anomaly toggles filter markers and click jumps to highlighted message', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-minimap-panel"]', { timeout: 10000 });

    const modelMarker = page.locator('[data-testid="timeline-anomaly-model_stall"]').first();
    const toolMarker = page.locator('[data-testid="timeline-anomaly-tool_error"]').first();
    await expect(modelMarker).toBeVisible();
    await expect(toolMarker).toBeVisible();
    await expect(modelMarker.locator('.timeline-minimap-anomaly-glyph')).toBeVisible();
    await expect(toolMarker.locator('.timeline-minimap-anomaly-glyph')).toBeVisible();
    await expect(page.locator('.timeline-minimap-legend')).toContainText('Model stall');
    await expect(page.locator('.timeline-minimap-legend')).toContainText('Tool error');

    const markerShape = await modelMarker.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { width: rect.width, height: rect.height };
    });
    expect(markerShape.width).toBeGreaterThan(markerShape.height + 8);

    await page.getByLabel('Toggle model stall anomalies').uncheck();
    await expect(page.locator('[data-testid="timeline-anomaly-model_stall"]')).toHaveCount(0);

    await page.getByLabel('Toggle model stall anomalies').check();
    await expect(page.locator('[data-testid="timeline-anomaly-model_stall"]').first()).toBeVisible();

    const beforeJump = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);
    await page.locator('[data-testid="timeline-anomaly-tool_error"]').first().click();
    await page.waitForTimeout(180);

    const afterJump = await page
      .locator('[data-testid="timeline-message-scroll"]')
      .evaluate((node) => (node as HTMLElement).scrollTop);
    expect(afterJump).toBeGreaterThan(beforeJump + 40);
    await expect(page.locator('.message-row-highlighted').first()).toBeVisible();
  });

  test('@full long session keeps windowed rendering size bounded while scrolling', async ({ page }) => {
    await setupLongTimelineMocks(page);
    await page.goto('/');

    await page.waitForSelector('tr[data-session-id="test-session-001"]', { timeout: 10000 });
    await page.locator('tr[data-session-id="test-session-001"]').click();
    await page.waitForSelector('[data-testid="timeline-message-scroll"]', { timeout: 10000 });

    const initialRenderedCount = await page.locator('.message-row').count();
    expect(initialRenderedCount).toBeGreaterThan(0);
    expect(initialRenderedCount).toBeLessThan(120);

    await page.locator('[data-testid="timeline-message-scroll"]').evaluate((node) => {
      const element = node as HTMLElement;
      element.scrollTop = element.scrollHeight;
      element.dispatchEvent(new Event('scroll'));
    });
    await page.waitForTimeout(140);

    const afterScrollRenderedCount = await page.locator('.message-row').count();
    expect(afterScrollRenderedCount).toBeGreaterThan(0);
    expect(afterScrollRenderedCount).toBeLessThan(120);
  });
});

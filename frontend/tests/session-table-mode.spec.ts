/**
 * E2E tests for compact session table mode.
 */

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const mockTableSessions = {
  sessions: [
    {
      session_id: 'session-alpha',
      ecosystem: 'claude_code',
      project_path: '/workspace/alpha',
      created_at: '2026-02-10T09:00:00Z',
      updated_at: '2026-02-10T11:00:00Z',
      total_messages: 28,
      total_tokens: 12000,
      git_branch: 'main',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 5400,
      bottleneck: 'Model',
      automation_ratio: 1.8,
    },
    {
      session_id: 'session-beta',
      ecosystem: 'codex',
      project_path: '/workspace/beta',
      created_at: '2026-02-08T08:00:00Z',
      updated_at: '2026-02-08T09:30:00Z',
      total_messages: 64,
      total_tokens: 50000,
      git_branch: 'feat/api',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 8400,
      bottleneck: 'Tool',
      automation_ratio: 3.2,
    },
    {
      session_id: 'session-gamma',
      ecosystem: 'claude_code',
      project_path: '/workspace/gamma',
      created_at: '2026-02-12T06:00:00Z',
      updated_at: '2026-02-12T12:15:00Z',
      total_messages: 18,
      total_tokens: 8000,
      git_branch: 'main',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 4200,
      bottleneck: 'User',
      automation_ratio: 0.9,
    },
  ],
  count: 3,
  page: 1,
  page_size: 200,
  total_pages: 1,
};

async function setupTableModeMockApi(page: Page): Promise<void> {
  await page.route(/\/api\/sessions(\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockTableSessions),
    });
  });

  await page.route(/\/api\/sessions\/session-[^/]+$/, async (route) => {
    const sessionId = route.request().url().split('/').pop() || 'session-alpha';
    const session = mockTableSessions.sessions.find((item) => item.session_id === sessionId);

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session: {
          metadata: {
            session_id: sessionId,
            project_path: session?.project_path || '/workspace/unknown',
            git_branch: session?.git_branch || 'main',
            version: session?.version || '1.0.0',
            created_at: session?.created_at || '2026-02-01T00:00:00Z',
            updated_at: session?.updated_at || '2026-02-01T00:00:00Z',
            total_messages: session?.total_messages || 0,
            total_tokens: session?.total_tokens || 0,
          },
          messages: [],
        },
      }),
    });
  });

  await page.route(/\/api\/sessions\/session-[^/]+\/statistics$/, async (route) => {
    const sessionId = route.request().url().split('/').at(-2) || 'session-alpha';
    const session = mockTableSessions.sessions.find((item) => item.session_id === sessionId);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        session_id: sessionId,
        statistics: {
          message_count: session?.total_messages || 0,
          user_message_count: 8,
          assistant_message_count: 10,
          system_message_count: 0,
          total_tokens: session?.total_tokens || 0,
          total_input_tokens: 4000,
          total_output_tokens: 4000,
          cache_read_tokens: 200,
          cache_creation_tokens: 100,
          tool_calls: [],
          tool_groups: [],
          total_tool_calls: 0,
          tool_error_records: [],
          tool_error_category_counts: {},
          error_taxonomy_version: '1.0.0',
          subagent_count: 0,
          subagent_sessions: {},
          session_duration_seconds: session?.duration_seconds || 0,
          first_message_time: session?.created_at || '2026-02-01T00:00:00Z',
          last_message_time: session?.updated_at || '2026-02-01T00:00:00Z',
        },
      }),
    });
  });
}

test.describe('@full Session Table Mode', () => {
  test('@smoke defaults to table view and renders semantic tags', async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.removeItem('agent-vis:session-browser:view-mode');
    });

    await setupTableModeMockApi(page);
    await page.goto('/');

    await expect(page.getByRole('button', { name: 'Table View' })).toHaveClass(/active/);
    await expect(page.locator('.session-table')).toBeVisible();
    await expect(page.locator('.session-tag--ecosystem-codex').first()).toBeVisible();
    await expect(page.locator('.session-tag--bottleneck-tool').first()).toBeVisible();
    await expect(page.locator('.session-tag--automation-high').first()).toBeVisible();

    const tokenCell = page.locator('tr[data-session-id="session-beta"] td').nth(4);
    await expect(tokenCell).toHaveText('50K');
    await expect(tokenCell).toHaveAttribute('title', '50,000');
  });

  test('should render compact table and open detail while preserving filters after back', async ({ page }) => {
    const requestedSessionDetails: string[] = [];
    page.on('request', (request) => {
      if (
        request.url().includes('/api/sessions/session-') &&
        !request.url().includes('/statistics')
      ) {
        requestedSessionDetails.push(request.url());
      }
    });

    await setupTableModeMockApi(page);
    await page.goto('/');

    await page.getByRole('button', { name: 'Table View' }).click();
    await page.waitForSelector('.session-table', { timeout: 10000 });
    await page.waitForSelector('tr[data-session-id="session-alpha"]', { timeout: 10000 });

    await expect(page.locator('.session-table thead')).toContainText('Ecosystem');
    await expect(page.locator('.session-table thead')).toContainText('Automation');

    const alphaRow = page.locator('tr[data-session-id="session-alpha"]');
    await alphaRow.click();
    await expect(page.getByRole('button', { name: 'Back to Overview' })).toBeVisible();
    await expect(page.locator('.detail-session-caption')).toContainText('session-alpha');

    await expect
      .poll(
        () => requestedSessionDetails.some((url) => url.includes('/api/sessions/session-alpha')),
        { timeout: 10000 }
      )
      .toBeTruthy();

    await page.getByRole('button', { name: 'Back to Overview' }).click();
    await page.waitForSelector('.session-table', { timeout: 10000 });

    await page.locator('.search-input').fill('session-alpha');
    await page.waitForTimeout(500);
    await expect(page.locator('.session-table tbody tr[data-session-id]')).toHaveCount(1);
    await expect(page.locator('tr[data-session-id="session-alpha"]')).toBeVisible();
  });

  test('should apply existing sort options in table mode', async ({ page }) => {
    await setupTableModeMockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'Table View' }).click();
    await page.waitForSelector('.session-table', { timeout: 10000 });

    await page.locator('.sort-select').selectOption('tokens');
    const firstByTokens = page.locator('.session-table tbody tr[data-session-id]').first();
    await expect(firstByTokens).toHaveAttribute('data-session-id', 'session-beta');

    await page.locator('.sort-select').selectOption('updated');
    const firstByUpdated = page.locator('.session-table tbody tr[data-session-id]').first();
    await expect(firstByUpdated).toHaveAttribute('data-session-id', 'session-gamma');
  });
});

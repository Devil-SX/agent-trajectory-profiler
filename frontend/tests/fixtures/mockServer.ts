/**
 * Mock server setup for Playwright tests
 */

import { Page } from '@playwright/test';
import { mockSessionList, mockSessionDetail, mockSessionStatistics } from './mockData';

/**
 * Setup mock API responses for tests
 */
export async function setupMockApi(page: Page) {
  const mockSyncStatus = {
    total_files: 22,
    total_sessions: 2,
    last_parsed_at: '2026-02-27T01:02:03.000Z',
    sync_running: false,
    last_sync: {
      status: 'completed',
      trigger: 'manual',
      started_at: '2026-02-27T01:01:00.000Z',
      finished_at: '2026-02-27T01:02:00.000Z',
      parsed: 5,
      skipped: 10,
      errors: 0,
      total_files_scanned: 15,
      total_file_size_bytes: 10240,
      ecosystems: [
        {
          ecosystem: 'claude_code',
          files_scanned: 10,
          file_size_bytes: 8192,
          parsed: 4,
          skipped: 6,
          errors: 0,
        },
        {
          ecosystem: 'codex',
          files_scanned: 5,
          file_size_bytes: 2048,
          parsed: 1,
          skipped: 4,
          errors: 0,
        },
      ],
      error_samples: [],
    },
  };

  // Mock sessions list endpoint
  await page.route(/\/api\/sessions(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionList),
    });
  });

  // Mock session detail endpoint
  await page.route('**/api/sessions/test-session-001', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionDetail),
    });
  });

  // Mock session statistics endpoint
  await page.route('**/api/sessions/test-session-001/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSessionStatistics),
    });
  });

  // Mock second session detail endpoint
  await page.route('**/api/sessions/test-session-002', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionDetail,
        session: {
          ...mockSessionDetail.session,
          metadata: {
            ...mockSessionDetail.session.metadata,
            session_id: 'test-session-002',
          },
        },
      }),
    });
  });

  // Mock second session statistics endpoint
  await page.route('**/api/sessions/test-session-002/statistics', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...mockSessionStatistics,
        session_id: 'test-session-002',
      }),
    });
  });

  await page.route(/\/api\/sync\/status(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus),
    });
  });

  await page.route(/\/api\/sync\/run(?:\?.*)?$/, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(mockSyncStatus.last_sync),
    });
  });
}

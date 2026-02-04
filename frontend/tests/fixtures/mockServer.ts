/**
 * Mock server setup for Playwright tests
 */

import { Page } from '@playwright/test';
import { mockSessionList, mockSessionDetail, mockSessionStatistics } from './mockData';

/**
 * Setup mock API responses for tests
 */
export async function setupMockApi(page: Page) {
  // Mock sessions list endpoint
  await page.route('**/api/sessions', async (route) => {
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
}

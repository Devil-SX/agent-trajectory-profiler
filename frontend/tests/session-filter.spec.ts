/**
 * E2E tests for SessionFilter component interactions.
 *
 * Tests cover:
 * - Search filtering sessions by project path and session ID
 * - Sort order toggling between all 5 options
 * - Bottleneck filter buttons (All, Model, Tool, User)
 * - Combined filter interactions
 * - Clearing search restores full list
 */

import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { SessionListResponse } from '../src/types/session';

/**
 * Extended mock session list with diverse data for filtering tests.
 * Includes different project paths, bottleneck types, token counts,
 * durations, and timestamps so each filter can be meaningfully tested.
 */
const filterMockSessionList: SessionListResponse = {
  sessions: [
    {
      session_id: 'session-alpha',
      project_path: '/home/user/frontend-app',
      created_at: '2024-02-05T10:00:00Z',
      updated_at: '2024-02-05T12:00:00Z',
      total_messages: 30,
      total_tokens: 20000,
      git_branch: 'main',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 7200,
      bottleneck: 'model',
      automation_ratio: 0.8,
    },
    {
      session_id: 'session-beta',
      project_path: '/home/user/backend-api',
      created_at: '2024-02-04T14:00:00Z',
      updated_at: '2024-02-04T16:30:00Z',
      total_messages: 50,
      total_tokens: 35000,
      git_branch: 'feature/auth',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 9000,
      bottleneck: 'tool',
      automation_ratio: 0.6,
    },
    {
      session_id: 'session-gamma',
      project_path: '/home/user/frontend-app',
      created_at: '2024-02-03T08:00:00Z',
      updated_at: '2024-02-03T09:00:00Z',
      total_messages: 10,
      total_tokens: 5000,
      git_branch: 'main',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 3600,
      bottleneck: 'user',
      automation_ratio: 0.3,
    },
    {
      session_id: 'session-delta',
      project_path: '/home/user/backend-api',
      created_at: '2024-02-02T20:00:00Z',
      updated_at: '2024-02-02T22:00:00Z',
      total_messages: 40,
      total_tokens: 28000,
      git_branch: 'develop',
      version: '1.0.0',
      parsed_at: null,
      duration_seconds: 7200,
      bottleneck: 'model',
      automation_ratio: 0.7,
    },
  ],
  count: 4,
  page: 1,
  page_size: 200,
  total_pages: 1,
};

/**
 * Set up mock API routes with the extended session list for filter tests.
 * Also mocks session detail and statistics endpoints so clicking a card
 * does not cause network errors.
 */
async function setupFilterMockApi(page: Page) {
  await page.route('**/api/sessions**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(filterMockSessionList),
    });
  });

  // Generic session detail mock to prevent errors on selection
  await page.route('**/api/sessions/session-*', async (route) => {
    const url = route.request().url();
    if (url.includes('/statistics')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session_id: 'session-alpha',
          statistics: {
            message_count: 30,
            user_message_count: 10,
            assistant_message_count: 20,
            system_message_count: 0,
            total_tokens: 20000,
            total_input_tokens: 14000,
            total_output_tokens: 6000,
            cache_read_tokens: 1000,
            cache_creation_tokens: 200,
            tool_calls: [],
            total_tool_calls: 0,
            subagent_count: 0,
            subagent_sessions: {},
            session_duration_seconds: 7200,
            first_message_time: '2024-02-05T10:00:00Z',
            last_message_time: '2024-02-05T12:00:00Z',
          },
        }),
      });
    } else {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: {
            metadata: {
              session_id: 'session-alpha',
              project_path: '/home/user/frontend-app',
              git_branch: 'main',
              version: '1.0.0',
              created_at: '2024-02-05T10:00:00Z',
              updated_at: '2024-02-05T12:00:00Z',
              total_messages: 30,
              total_tokens: 20000,
            },
            messages: [],
          },
        }),
      });
    }
  });
}

/** Wait for the session browser and all session cards to render. */
async function waitForSessions(page: Page) {
  await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
  await page.waitForSelector('.session-card', { state: 'visible', timeout: 5000 });
}

test.describe('@full Session Filter - Search', () => {
  test('should filter sessions by project path', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // All 4 sessions visible initially
    await expect(page.locator('.session-card')).toHaveCount(4);

    // Type a search query matching "frontend-app"
    await page.locator('.search-input').fill('frontend-app');

    // Wait for debounce (300ms) + rendering
    await page.waitForTimeout(500);

    // Only 2 sessions should match (alpha and gamma)
    await expect(page.locator('.session-card')).toHaveCount(2);
  });

  test('should filter sessions by session ID', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.search-input').fill('session-beta');
    await page.waitForTimeout(500);

    await expect(page.locator('.session-card')).toHaveCount(1);
  });

  test('should show no results for non-matching search', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.search-input').fill('nonexistent-project-xyz');
    await page.waitForTimeout(500);

    await expect(page.locator('.session-card')).toHaveCount(0);

    // Session count should show "0 of 4 sessions"
    await expect(page.locator('.session-count')).toContainText('0 of 4');
  });

  test('should be case-insensitive', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.search-input').fill('FRONTEND-APP');
    await page.waitForTimeout(500);

    // Same 2 sessions as lowercase search
    await expect(page.locator('.session-card')).toHaveCount(2);
  });

  test('should restore full list when search is cleared', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Filter down
    const searchInput = page.locator('.search-input');
    await searchInput.fill('backend-api');
    await page.waitForTimeout(500);
    await expect(page.locator('.session-card')).toHaveCount(2);

    // Clear the search
    await searchInput.fill('');
    await page.waitForTimeout(500);

    // All sessions should return
    await expect(page.locator('.session-card')).toHaveCount(4);
    await expect(page.locator('.session-count')).toContainText('4 of 4');
  });
});

test.describe('@full Session Filter - Sort', () => {
  test('should default to "Updated (newest first)" sort', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    const sortSelect = page.locator('.sort-select');
    await expect(sortSelect).toHaveValue('updated');
  });

  test('should sort by created date', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.sort-select').selectOption('created');

    // First card should be the most recently created (session-alpha: Feb 5)
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('frontend-app');
  });

  test('should sort by token usage', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.sort-select').selectOption('tokens');

    // First card should be session-beta (highest tokens: 35000)
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('backend-api');
  });

  test('should sort by duration', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.sort-select').selectOption('duration');

    // First card should be session-beta (longest duration: 9000s)
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('backend-api');
  });

  test('should sort by automation ratio', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.sort-select').selectOption('automation');

    // First card should be session-alpha (highest automation: 0.8)
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('frontend-app');
  });
});

test.describe('@full Session Filter - Bottleneck', () => {
  test('should show all sessions when "All" bottleneck is selected', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // "All" button should be active by default
    const allButton = page.locator('.filter-button--all');
    await expect(allButton).toHaveClass(/filter-button--active/);

    await expect(page.locator('.session-card')).toHaveCount(4);
  });

  test('should filter by "Model" bottleneck', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.filter-button--model').click();
    await page.waitForTimeout(200);

    // 2 sessions have bottleneck "model" (alpha and delta)
    await expect(page.locator('.session-card')).toHaveCount(2);

    // Model button should now be active
    await expect(page.locator('.filter-button--model')).toHaveClass(/filter-button--active/);
  });

  test('should filter by "Tool" bottleneck', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.filter-button--tool').click();
    await page.waitForTimeout(200);

    // 1 session has bottleneck "tool" (beta)
    await expect(page.locator('.session-card')).toHaveCount(1);
  });

  test('should filter by "User" bottleneck', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await page.locator('.filter-button--user').click();
    await page.waitForTimeout(200);

    // 1 session has bottleneck "user" (gamma)
    await expect(page.locator('.session-card')).toHaveCount(1);
  });

  test('should return to all sessions when clicking "All" after filtering', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Filter to model only
    await page.locator('.filter-button--model').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.session-card')).toHaveCount(2);

    // Click All to reset
    await page.locator('.filter-button--all').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.session-card')).toHaveCount(4);
  });
});

test.describe('@full Session Filter - Combined Filters', () => {
  test('should apply search and bottleneck filter together', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Filter by bottleneck "model" -> alpha and delta
    await page.locator('.filter-button--model').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.session-card')).toHaveCount(2);

    // Also search for "frontend-app" -> only alpha remains
    await page.locator('.search-input').fill('frontend-app');
    await page.waitForTimeout(500);
    await expect(page.locator('.session-card')).toHaveCount(1);
  });

  test('should apply search and sort together', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Search for "backend-api" -> beta and delta
    await page.locator('.search-input').fill('backend-api');
    await page.waitForTimeout(500);
    await expect(page.locator('.session-card')).toHaveCount(2);

    // Sort by tokens -> beta (35000) should come before delta (28000)
    await page.locator('.sort-select').selectOption('tokens');
    await page.waitForTimeout(200);

    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('feature/auth');
  });

  test('should show correct session count with combined filters', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Verify initial count
    await expect(page.locator('.session-count')).toContainText('4 of 4');

    // Apply bottleneck filter
    await page.locator('.filter-button--tool').click();
    await page.waitForTimeout(200);
    await expect(page.locator('.session-count')).toContainText('1 of 4');

    // Reset bottleneck, apply search
    await page.locator('.filter-button--all').click();
    await page.waitForTimeout(200);
    await page.locator('.search-input').fill('frontend');
    await page.waitForTimeout(500);
    await expect(page.locator('.session-count')).toContainText('2 of 4');
  });

  test('should maintain sort order when changing bottleneck filter', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    // Set sort to tokens
    await page.locator('.sort-select').selectOption('tokens');
    await page.waitForTimeout(200);

    // Apply model bottleneck filter -> alpha (20000) and delta (28000)
    await page.locator('.filter-button--model').click();
    await page.waitForTimeout(200);

    // delta (28000) should come before alpha (20000) since sorted by tokens desc
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toContainText('backend-api');
  });
});

test.describe('@full Session Filter - UI State', () => {
  test('should display all filter controls', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await expect(page.locator('.search-input')).toBeVisible();
    await expect(page.locator('.sort-select')).toBeVisible();
    await expect(page.locator('.filter-button--all')).toBeVisible();
    await expect(page.locator('.filter-button--model')).toBeVisible();
    await expect(page.locator('.filter-button--tool')).toBeVisible();
    await expect(page.locator('.filter-button--user')).toBeVisible();
  });

  test('should show search placeholder text', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    await expect(page.locator('.search-input')).toHaveAttribute(
      'placeholder',
      /search/i
    );
  });

  test('should display sort dropdown with all options', async ({ page }) => {
    await setupFilterMockApi(page);
    await page.goto('/');
    await waitForSessions(page);

    const options = page.locator('.sort-select option');
    await expect(options).toHaveCount(5);
  });
});

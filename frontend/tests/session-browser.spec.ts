/**
 * E2E tests for SessionBrowser component
 *
 * Tests cover:
 * - Rendering SessionBrowser and its child components (SessionFilter, SessionListView)
 * - Displaying session count
 * - Loading state display
 * - Empty state display
 * - Error state display
 * - Session card rendering within the browser
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('SessionBrowser - Rendering', () => {
  test('should render the session browser container', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-browser', { timeout: 5000 });
    const browser = page.locator('.session-browser');
    await expect(browser).toBeVisible();
  });

  test('should render session filter controls', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });

    // SessionFilter child component should be rendered
    const filterSection = page.locator('.session-browser-filter');
    await expect(filterSection).toBeVisible();
  });

  test('should render session list view', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });

    // SessionListView child component should be rendered
    const listSection = page.locator('.session-browser-list');
    await expect(listSection).toBeVisible();
  });

  test('should render session cards inside the browser', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
    await page.waitForSelector('.session-card', { state: 'visible' });

    const cards = page.locator('.session-card');
    const count = await cards.count();
    expect(count).toBe(2); // mockSessionList has 2 sessions
  });
});

test.describe('SessionBrowser - Session Count', () => {
  test('should display correct session count', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-count', { timeout: 5000 });

    const countText = await page.locator('.session-count').textContent();
    expect(countText).toContain('2');
    expect(countText).toContain('sessions');
  });

  test('should display "N of N sessions" format', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-count', { timeout: 5000 });

    // Format is "N of N sessions" (e.g., "2 of 2 sessions")
    await expect(page.locator('.session-count')).toContainText('2 of 2 sessions');
  });
});

test.describe('SessionBrowser - Loading State', () => {
  test('should display loading state while fetching sessions', async ({ page }) => {
    // Delay the API response to capture loading state
    await page.route('**/api/sessions', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');

    // Loading state should show .session-browser.loading
    const loadingBrowser = page.locator('.session-browser.loading');
    await expect(loadingBrowser).toBeVisible({ timeout: 3000 });

    // Loading container should have loading text
    const loadingText = page.locator('.loading-container');
    await expect(loadingText).toContainText('Loading sessions');
  });

  test('should not show session cards during loading', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.loading', { timeout: 3000 });

    // No session cards should be visible during loading
    const cards = page.locator('.session-card');
    expect(await cards.count()).toBe(0);
  });
});

test.describe('SessionBrowser - Empty State', () => {
  test('should display empty state when no sessions are returned', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');

    const emptyBrowser = page.locator('.session-browser.empty');
    await expect(emptyBrowser).toBeVisible({ timeout: 5000 });
  });

  test('should show "No sessions available" message in empty state', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.empty', { timeout: 5000 });

    const emptyContainer = page.locator('.empty-container');
    await expect(emptyContainer).toContainText('No sessions available');
  });

  test('should not show session count in empty state', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.empty', { timeout: 5000 });

    // Session count element should not be present in empty state
    const sessionCount = page.locator('.session-count');
    expect(await sessionCount.count()).toBe(0);
  });
});

test.describe('SessionBrowser - Error State', () => {
  test('should display error state when API returns 500', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');

    const errorBrowser = page.locator('.session-browser.error');
    await expect(errorBrowser).toBeVisible({ timeout: 5000 });
  });

  test('should show error message in error state', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.error', { timeout: 5000 });

    const errorMessage = page.locator('.error-message');
    await expect(errorMessage).toBeVisible();
    const text = await errorMessage.textContent();
    expect(text).toBeTruthy();
  });

  test('should show error container with styling', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.error', { timeout: 5000 });

    const errorContainer = page.locator('.error-container');
    await expect(errorContainer).toBeVisible();
  });

  test('should not show session cards in error state', async ({ page }) => {
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');

    await page.waitForSelector('.session-browser.error', { timeout: 5000 });

    const cards = page.locator('.session-card');
    expect(await cards.count()).toBe(0);
  });
});

test.describe('SessionBrowser - Auto-selection', () => {
  test('should auto-select first session on load', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });

    // First card should be selected
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toHaveClass(/session-card--selected/);
  });

  test('should transition from loading to loaded state', async ({ page }) => {
    // Use a short delay to observe the transition
    await page.route('**/api/sessions', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [
            {
              session_id: 'test-session-001',
              project_path: '/home/user/project',
              created_at: '2024-02-01T10:00:00Z',
              updated_at: '2024-02-01T11:30:00Z',
              total_messages: 25,
              total_tokens: 15000,
              git_branch: 'main',
              version: '1.0.0',
            },
          ],
          count: 1,
        }),
      });
    });

    // Mock session detail for auto-selection
    await page.route('**/api/sessions/test-session-001', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session: { metadata: {}, messages: [] } }),
      });
    });

    await page.route('**/api/sessions/test-session-001/statistics', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ session_id: 'test-session-001', statistics: {} }),
      });
    });

    await page.goto('/');

    // Should eventually show the non-loading state with content
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
    await page.waitForSelector('.session-card', { state: 'visible', timeout: 5000 });

    const cards = page.locator('.session-card');
    expect(await cards.count()).toBe(1);
  });
});

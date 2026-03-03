/**
 * E2E tests for SessionCard interaction behavior
 *
 * Tests cover:
 * - Default selection of first card
 * - Click to change selection
 * - Loading session details on selection
 * - Displaying card content (title, stats, ID)
 * - Showing bottleneck badges
 * - Fast consecutive clicks without crashes
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@full SessionCard - Default Selection', () => {
  test('should select the first card by default on page load', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for session cards to render
    await page.waitForSelector('.session-card', { state: 'visible', timeout: 5000 });

    // First card should have the selected class
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toHaveClass(/session-card--selected/);

    // Only one card should be selected
    const selectedCards = page.locator('.session-card--selected');
    await expect(selectedCards).toHaveCount(1);
  });

  test('should load session details for the first card automatically', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });

    // Session detail content should appear (timeline or statistics)
    await page.waitForSelector('.message-timeline, .statistics-dashboard', { timeout: 5000 });
  });
});

test.describe('@full SessionCard - Click to Change Selection', () => {
  test('should select second card when clicked', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for initial selection
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click the second card
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();
    await page.waitForTimeout(500);

    // Second card should now be selected
    await expect(secondCard).toHaveClass(/session-card--selected/);

    // First card should no longer be selected
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).not.toHaveClass(/session-card--selected/);

    // Still only one card selected
    const selectedCards = page.locator('.session-card--selected');
    await expect(selectedCards).toHaveCount(1);
  });

  test('should load new session details after switching cards', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for first session to fully load
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForSelector('.message-timeline, .statistics-dashboard', { timeout: 5000 });

    // Click the second card
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();

    // Content area should update (detail content should still be present)
    await page.waitForSelector('.message-timeline, .statistics-dashboard', { timeout: 5000 });
  });
});

test.describe('@full SessionCard - Display Content', () => {
  test('should display card title with project name and bullet separators', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card__title', { state: 'visible', timeout: 5000 });

    const titleText = await page.locator('.session-card__title').first().textContent();
    // Title format is "projectName • branch • relativeTime" with bullet separators
    expect(titleText).toContain('\u2022');
  });

  test('should display statistics (Tokens, Automation, Messages)', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card__stats', { state: 'visible', timeout: 5000 });

    const firstCard = page.locator('.session-card').first();

    // Check stat labels are present
    const statLabels = firstCard.locator('.session-card__stat-label');
    await expect(statLabels).toHaveCount(3);

    // Check that Tokens, Automation, Messages labels exist
    const labelsText = await statLabels.allTextContents();
    expect(labelsText.map((l) => l.toLowerCase())).toEqual(
      expect.arrayContaining(['tokens', 'automation', 'messages']),
    );

    // Check stat values are non-empty
    const statValues = firstCard.locator('.session-card__stat-value');
    await expect(statValues).toHaveCount(3);
    for (let i = 0; i < 3; i++) {
      const valueText = await statValues.nth(i).textContent();
      expect(valueText?.trim().length).toBeGreaterThan(0);
    }
  });

  test('should display session ID in footer', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card__session-id', { state: 'visible', timeout: 5000 });

    const sessionIdEl = page.locator('.session-card__session-id').first();
    const idText = await sessionIdEl.textContent();
    // Session ID should be a truncated 8-char string (from "test-session-001" -> "test-ses")
    expect(idText?.trim().length).toBeGreaterThan(0);
    expect(idText?.trim().length).toBeLessThanOrEqual(8);
  });
});

test.describe('@full SessionCard - Bottleneck Badges', () => {
  test('should display bottleneck badge when session has a bottleneck', async ({ page }) => {
    // Override the mock to include bottleneck data
    await page.route('**/api/sessions', async (route) => {
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
              bottleneck: 'Model',
              automation_ratio: 3.5,
              duration_seconds: 5400,
              parsed_at: '2024-02-01T12:00:00Z',
            },
            {
              session_id: 'test-session-002',
              project_path: '/home/user/project',
              created_at: '2024-02-02T14:00:00Z',
              updated_at: '2024-02-02T15:45:00Z',
              total_messages: 40,
              total_tokens: 25000,
              git_branch: 'feature/new-feature',
              version: '1.0.0',
              bottleneck: 'Tool',
              automation_ratio: 2.1,
              duration_seconds: 6300,
              parsed_at: '2024-02-02T16:00:00Z',
            },
          ],
          count: 2,
          page: 1,
          page_size: 50,
          total_pages: 1,
        }),
      });
    });

    // Also set up session detail and statistics routes
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { state: 'visible', timeout: 5000 });

    // Check that bottleneck badges are visible
    const badges = page.locator('.session-card__bottleneck-badge');
    const badgeCount = await badges.count();
    expect(badgeCount).toBeGreaterThan(0);

    // Verify the bottleneck text
    const firstBadgeText = await badges.first().textContent();
    expect(firstBadgeText?.trim()).toBe('Model');
  });

  test('should not display bottleneck badge when session has no bottleneck', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { state: 'visible', timeout: 5000 });

    // Default mock data has no bottleneck field, so badges should not appear
    const firstCard = page.locator('.session-card').first();
    const badge = firstCard.locator('.session-card__bottleneck-badge');
    await expect(badge).toHaveCount(0);
  });
});

test.describe('@full SessionCard - Fast Consecutive Clicks', () => {
  test('should handle rapid clicks between cards without crashing', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    const firstCard = page.locator('.session-card').first();
    const secondCard = page.locator('.session-card').nth(1);

    // Rapidly alternate clicks between cards
    for (let i = 0; i < 5; i++) {
      await secondCard.click();
      await firstCard.click();
    }

    // Wait a moment for any pending state updates
    await page.waitForTimeout(1000);

    // Page should not have crashed - verify cards are still visible
    await expect(firstCard).toBeVisible();
    await expect(secondCard).toBeVisible();

    // Exactly one card should be selected
    const selectedCards = page.locator('.session-card--selected');
    await expect(selectedCards).toHaveCount(1);

    // Content area should still be functional
    await page.waitForSelector('.message-timeline, .statistics-dashboard', { timeout: 5000 });
  });

  test('should handle double-click on the same card gracefully', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    const firstCard = page.locator('.session-card').first();

    // Double-click the already-selected card
    await firstCard.dblclick();
    await page.waitForTimeout(500);

    // Card should remain selected, no crash
    await expect(firstCard).toHaveClass(/session-card--selected/);

    // Only one card should be selected
    const selectedCards = page.locator('.session-card--selected');
    await expect(selectedCards).toHaveCount(1);
  });
});

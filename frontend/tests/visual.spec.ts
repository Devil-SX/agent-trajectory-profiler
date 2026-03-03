/**
 * Playwright visual tests for Claude Code Session Visualizer
 *
 * Tests cover:
 * - Home page screenshot
 * - Session card interactions
 * - Timeline with messages
 * - Sidebar statistics visualization
 * - Mobile viewport screenshots
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@manual Home Page', () => {
  test('should display home page with session browser', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for SessionBrowser to load
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
    await page.waitForSelector('.session-card', { state: 'visible' });
    await expect(page.locator('h1')).toContainText('Claude Code Session Visualizer');

    // Take screenshot of home page
    await page.screenshot({
      path: 'tests/screenshots/01-home-page.png',
      fullPage: true,
    });
  });

  test('should display loading state', async ({ page }) => {
    // Delay the response to capture loading state
    await page.route('**/api/sessions', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 1000));
      await route.continue();
    });

    const loadingPromise = page.goto('/');

    // Try to capture loading state
    const isLoading = await page.locator('.session-browser.loading').isVisible().catch(() => false);

    if (isLoading) {
      await page.screenshot({
        path: 'tests/screenshots/02-loading-state.png',
      });
    }

    await loadingPromise;
  });

  test('should display no session selected state', async ({ page }) => {
    // Mock empty sessions list
    await page.route('**/api/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ sessions: [], count: 0 }),
      });
    });

    await page.goto('/');
    await page.waitForSelector('.session-browser.empty, .no-session, .empty', { timeout: 3000 });

    await page.screenshot({
      path: 'tests/screenshots/03-no-sessions.png',
      fullPage: true,
    });
  });
});

test.describe('@manual Session Selection', () => {
  test('should select and display first session by default', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for first session card to be selected
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForSelector('.message-timeline, .session-content', { timeout: 5000 });

    // Verify first card is selected
    const firstCard = page.locator('.session-card').first();
    await expect(firstCard).toHaveClass(/session-card--selected/);

    await page.screenshot({
      path: 'tests/screenshots/04-first-session-selected.png',
      fullPage: true,
    });
  });

  test('should change sessions when clicking a card', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for first session to load
    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Take screenshot before change
    await page.screenshot({
      path: 'tests/screenshots/05-before-session-change.png',
      fullPage: true,
    });

    // Click second session card
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();
    await page.waitForTimeout(1000);

    // Verify second card is now selected
    await expect(secondCard).toHaveClass(/session-card--selected/);

    // Take screenshot after change
    await page.screenshot({
      path: 'tests/screenshots/06-after-session-change.png',
      fullPage: true,
    });

    // Verify multiple cards exist
    const cardCount = await page.locator('.session-card').count();
    expect(cardCount).toBeGreaterThan(1);
  });

  test('should display session info', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-count', { timeout: 5000 });
    await expect(page.locator('.session-count')).toContainText('2 sessions');

    await page.screenshot({
      path: 'tests/screenshots/07-session-info.png',
    });
  });
});

test.describe('@manual Timeline View', () => {
  test('should display timeline with messages', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    // Wait for timeline to load
    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // Verify messages are displayed
    const messages = await page.locator('.message-bubble').count();
    expect(messages).toBeGreaterThan(0);

    await page.screenshot({
      path: 'tests/screenshots/08-timeline-view.png',
      fullPage: true,
    });
  });

  test('should display user and assistant messages differently', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // Take screenshot showing message differentiation
    await page.screenshot({
      path: 'tests/screenshots/09-message-types.png',
      fullPage: true,
    });
  });

  test('should display tool calls in timeline', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // Scroll to see more messages
    await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight / 2));
    await page.waitForTimeout(300);

    await page.screenshot({
      path: 'tests/screenshots/10-tool-calls.png',
      fullPage: true,
    });
  });
});

test.describe('@manual Statistics View', () => {
  test('should display statistics dashboard', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click statistics tab
    await page.click('button:has-text("Statistics")');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: 'tests/screenshots/11-statistics-dashboard.png',
      fullPage: true,
    });
  });

  test('should display statistics charts', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click statistics tab
    await page.click('button:has-text("Statistics")');
    await page.waitForTimeout(1500);

    // Look for chart elements (Recharts renders SVG)
    const hasSvg = (await page.locator('svg.recharts-surface').count()) > 0;

    if (hasSvg) {
      await page.screenshot({
        path: 'tests/screenshots/12-statistics-charts.png',
        fullPage: true,
      });
    } else {
      // Fallback if charts aren't rendering
      await page.screenshot({
        path: 'tests/screenshots/12-statistics-charts.png',
        fullPage: true,
      });
    }
  });
});

test.describe('@manual Cross-Session Analytics View', () => {
  test('should display cross-session analytics view', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click cross-session analytics tab
    await page.click('button:has-text("Cross-Session Analytics")');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: 'tests/screenshots/13-advanced-analytics.png',
      fullPage: true,
    });
  });

  test('should display comparison selector in analytics', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click cross-session analytics tab
    await page.click('button:has-text("Cross-Session Analytics")');
    await page.waitForTimeout(500);

    // Verify comparison selector is visible
    const comparisonSelect = await page.locator('#comparison-select').isVisible();
    expect(comparisonSelect).toBe(true);

    await page.screenshot({
      path: 'tests/screenshots/14-comparison-selector.png',
      fullPage: true,
    });
  });
});

test.describe('@manual Sidebar', () => {
  test('should display session metadata sidebar', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(1000);

    // Check if sidebar is visible
    const sidebarVisible = await page.locator('.sidebar-container, .session-metadata-sidebar').isVisible();

    if (sidebarVisible) {
      await page.screenshot({
        path: 'tests/screenshots/15-sidebar-metadata.png',
        fullPage: true,
      });
    } else {
      // Take screenshot anyway for debugging
      await page.screenshot({
        path: 'tests/screenshots/15-sidebar-metadata.png',
        fullPage: true,
      });
    }
  });
});

test.describe('@manual Tab Navigation', () => {
  test('should navigate between tabs', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card--selected', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Verify Timeline tab is active by default
    await expect(page.locator('button.tab-button.active')).toContainText('Timeline');

    // Click Statistics tab
    await page.click('button:has-text("Statistics")');
    await page.waitForTimeout(500);
    await expect(page.locator('button.tab-button.active')).toContainText('Statistics');

    // Click Cross-Session Analytics tab
    await page.click('button:has-text("Cross-Session Analytics")');
    await page.waitForTimeout(500);
    await expect(page.locator('button.tab-button.active')).toContainText('Cross-Session Analytics');

    // Click back to Timeline
    await page.click('button:has-text("Timeline")');
    await page.waitForTimeout(500);
    await expect(page.locator('button.tab-button.active')).toContainText('Timeline');

    await page.screenshot({
      path: 'tests/screenshots/16-tab-navigation.png',
      fullPage: true,
    });
  });
});

test.describe('@manual Mobile View', () => {
  test.use({ viewport: { width: 375, height: 667 } }); // iPhone SE size

  test('should display mobile home page', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { timeout: 5000 });
    await page.waitForTimeout(500);

    await page.screenshot({
      path: 'tests/screenshots/mobile-01-home.png',
      fullPage: true,
    });
  });

  test('should display mobile timeline view', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: 'tests/screenshots/mobile-02-timeline.png',
      fullPage: true,
    });
  });

  test('should show mobile sidebar toggle button', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Look for mobile sidebar toggle
    const toggleButton = page.locator('button.mobile-sidebar-toggle');
    const isVisible = await toggleButton.isVisible().catch(() => false);

    if (isVisible) {
      await page.screenshot({
        path: 'tests/screenshots/mobile-03-sidebar-toggle.png',
        fullPage: true,
      });

      // Click to open sidebar
      await toggleButton.click();
      await page.waitForTimeout(500);

      await page.screenshot({
        path: 'tests/screenshots/mobile-04-sidebar-open.png',
        fullPage: true,
      });
    } else {
      // Take screenshot anyway
      await page.screenshot({
        path: 'tests/screenshots/mobile-03-sidebar-toggle.png',
        fullPage: true,
      });
    }
  });

  test('should display mobile statistics view', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { timeout: 5000 });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Statistics")');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: 'tests/screenshots/mobile-05-statistics.png',
      fullPage: true,
    });
  });

  test('should display mobile analytics view', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { timeout: 5000 });
    await page.waitForTimeout(500);

    await page.click('button:has-text("Cross-Session Analytics")');
    await page.waitForTimeout(1000);

    await page.screenshot({
      path: 'tests/screenshots/mobile-06-analytics.png',
      fullPage: true,
    });
  });

  test('should handle session selection on mobile', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');

    await page.waitForSelector('.session-card', { timeout: 5000 });
    await page.waitForTimeout(500);

    // Click first card
    const firstCard = page.locator('.session-card').first();
    await firstCard.click();
    await page.waitForTimeout(200);

    await page.screenshot({
      path: 'tests/screenshots/mobile-07-session-selected.png',
      fullPage: true,
    });

    // Click second session card
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();
    await page.waitForTimeout(1000);

    // Verify second card is selected
    await expect(secondCard).toHaveClass(/session-card--selected/);

    await page.screenshot({
      path: 'tests/screenshots/mobile-08-session-changed.png',
      fullPage: true,
    });

    // Verify multiple cards exist
    const cardCount = await page.locator('.session-card').count();
    expect(cardCount).toBeGreaterThan(1);
  });
});

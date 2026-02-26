/**
 * E2E tests for tab navigation functionality
 *
 * Tests cover:
 * - Default Timeline tab display
 * - Switching to Statistics tab
 * - Switching to Advanced Analytics tab
 * - Tab state persistence when changing sessions
 * - Fast tab switching without crashes
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

/**
 * Helper: wait for a session to be selected and tabs to appear
 */
async function waitForTabsReady(page: import('@playwright/test').Page) {
  await page.waitForSelector('.session-card--selected', { timeout: 5000 });
  await page.waitForSelector('.view-tabs', { timeout: 5000 });
}

test.describe('Tab Navigation', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForTabsReady(page);
  });

  test('should display Timeline tab as active by default', async ({ page }) => {
    // Timeline tab should be active by default
    const activeTab = page.locator('button.tab-button.active');
    await expect(activeTab).toContainText('Timeline');

    // Timeline content should be visible
    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await expect(page.locator('.message-timeline')).toBeVisible();
  });

  test('should display all three tab buttons', async ({ page }) => {
    const tabs = page.locator('button.tab-button');
    // At minimum: Timeline, Statistics, Advanced Analytics (mobile may add sidebar toggle)
    const count = await tabs.count();
    expect(count).toBeGreaterThanOrEqual(3);

    await expect(page.locator('button.tab-button:has-text("Timeline")')).toBeVisible();
    await expect(page.locator('button.tab-button:has-text("Statistics")')).toBeVisible();
    await expect(page.locator('button.tab-button:has-text("Advanced Analytics")')).toBeVisible();
  });

  test('should switch to Statistics tab', async ({ page }) => {
    // Click Statistics tab
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForTimeout(500);

    // Statistics tab should be active
    const activeTab = page.locator('button.tab-button.active');
    await expect(activeTab).toContainText('Statistics');

    // Timeline tab should no longer be active
    const timelineTab = page.locator('button.tab-button:has-text("Timeline")');
    await expect(timelineTab).not.toHaveClass(/active/);

    // Statistics content should be visible
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });
    await expect(page.locator('.statistics-dashboard')).toBeVisible();

    // Timeline content should not be visible
    await expect(page.locator('.message-timeline')).not.toBeVisible();
  });

  test('should switch to Advanced Analytics tab', async ({ page }) => {
    // Click Advanced Analytics tab
    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForTimeout(500);

    // Advanced Analytics tab should be active
    const activeTab = page.locator('button.tab-button.active');
    await expect(activeTab).toContainText('Advanced Analytics');

    // Advanced Analytics content should be visible
    await page.waitForSelector('.advanced-analytics', { timeout: 5000 });
    await expect(page.locator('.advanced-analytics')).toBeVisible();

    // Other views should not be visible
    await expect(page.locator('.message-timeline')).not.toBeVisible();
    await expect(page.locator('.statistics-dashboard')).not.toBeVisible();
  });

  test('should navigate back to Timeline from another tab', async ({ page }) => {
    // Switch away from Timeline
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForTimeout(500);
    await expect(page.locator('button.tab-button.active')).toContainText('Statistics');

    // Switch back to Timeline
    await page.click('button.tab-button:has-text("Timeline")');
    await page.waitForTimeout(500);

    // Timeline tab should be active again
    await expect(page.locator('button.tab-button.active')).toContainText('Timeline');

    // Timeline content should be visible
    await page.waitForSelector('.message-timeline', { timeout: 5000 });
    await expect(page.locator('.message-timeline')).toBeVisible();
  });

  test('should cycle through all tabs without errors', async ({ page }) => {
    // Timeline -> Statistics -> Advanced Analytics -> Timeline
    const tabSequence = ['Statistics', 'Advanced Analytics', 'Timeline'];
    const contentSelectors = ['.statistics-dashboard', '.advanced-analytics', '.message-timeline'];

    for (let i = 0; i < tabSequence.length; i++) {
      await page.click(`button.tab-button:has-text("${tabSequence[i]}")`);
      await page.waitForTimeout(500);

      await expect(page.locator('button.tab-button.active')).toContainText(tabSequence[i]);
      await page.waitForSelector(contentSelectors[i], { timeout: 5000 });
      await expect(page.locator(contentSelectors[i])).toBeVisible();
    }
  });

  test('should only have one active tab at a time', async ({ page }) => {
    // Check initial state: exactly one active tab
    let activeCount = await page.locator('button.tab-button.active').count();
    expect(activeCount).toBe(1);

    // Switch to Statistics
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForTimeout(300);
    activeCount = await page.locator('button.tab-button.active').count();
    expect(activeCount).toBe(1);

    // Switch to Advanced Analytics
    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForTimeout(300);
    activeCount = await page.locator('button.tab-button.active').count();
    expect(activeCount).toBe(1);
  });
});

test.describe('Tab State on Session Change', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForTabsReady(page);
  });

  test('should preserve tab state when switching sessions', async ({ page }) => {
    // Switch to Statistics tab
    await page.click('button.tab-button:has-text("Statistics")');
    await page.waitForTimeout(500);
    await expect(page.locator('button.tab-button.active')).toContainText('Statistics');

    // Click second session card
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();
    await page.waitForTimeout(1000);

    // Verify second card is now selected
    await expect(secondCard).toHaveClass(/session-card--selected/);

    // Tab state should persist -- Statistics should still be active
    await expect(page.locator('button.tab-button.active')).toContainText('Statistics');
  });

  test('should load correct content for new session after tab switch', async ({ page }) => {
    // Switch to Advanced Analytics
    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForSelector('.advanced-analytics', { timeout: 5000 });

    // Switch to second session
    const secondCard = page.locator('.session-card').nth(1);
    await secondCard.click();
    await page.waitForTimeout(1000);

    // Advanced Analytics should still be visible for the new session
    await expect(page.locator('.advanced-analytics')).toBeVisible();
    await expect(page.locator('button.tab-button.active')).toContainText('Advanced Analytics');
  });
});

test.describe('Fast Tab Switching', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await waitForTabsReady(page);
  });

  test('should handle rapid tab switching without crashes', async ({ page }) => {
    // Rapidly click through tabs without waiting for content to load
    const tabs = ['Statistics', 'Advanced Analytics', 'Timeline', 'Statistics', 'Timeline', 'Advanced Analytics'];

    for (const tab of tabs) {
      await page.click(`button.tab-button:has-text("${tab}")`);
      // Minimal delay -- just enough for the click to register
      await page.waitForTimeout(50);
    }

    // After rapid switching, the last clicked tab should be active
    await page.waitForTimeout(500);
    const lastTab = tabs[tabs.length - 1];
    await expect(page.locator('button.tab-button.active')).toContainText(lastTab);

    // Page should not have crashed -- check for a basic element
    await expect(page.locator('h1')).toContainText('Claude Code Session Visualizer');
  });

  test('should settle on correct content after rapid switching', async ({ page }) => {
    // Rapidly switch and end on Statistics
    await page.click('button.tab-button:has-text("Advanced Analytics")');
    await page.waitForTimeout(30);
    await page.click('button.tab-button:has-text("Timeline")');
    await page.waitForTimeout(30);
    await page.click('button.tab-button:has-text("Statistics")');

    // Wait for content to settle
    await page.waitForTimeout(1000);

    // Statistics should be the final active tab and its content should be visible
    await expect(page.locator('button.tab-button.active')).toContainText('Statistics');
    await page.waitForSelector('.statistics-dashboard', { timeout: 5000 });
    await expect(page.locator('.statistics-dashboard')).toBeVisible();
  });
});

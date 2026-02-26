/**
 * E2E test for session loading functionality
 *
 * Tests the actual API connection and session browser functionality
 * without mocks - validates real backend integration.
 */

import { test, expect } from '@playwright/test';

test.describe('Session Loading Integration', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to home page
    await page.goto('/');
  });

  test('should load sessions from API and display session browser', async ({ page }) => {
    // Wait for the session browser to appear (not loading state)
    await page.waitForSelector('.session-browser', {
      state: 'visible',
      timeout: 10000
    });

    // Should not be stuck in loading state
    const loadingText = await page.locator('.session-browser').textContent();
    expect(loadingText).not.toContain('Loading sessions...');

    // Should display session cards
    const sessionCards = page.locator('.session-card');
    const cardCount = await sessionCards.count();

    // Should have at least one session
    expect(cardCount).toBeGreaterThan(0);

    console.log(`✅ Found ${cardCount} session cards`);
  });

  test('should display session filter controls', async ({ page }) => {
    // Wait for filter to load
    await page.waitForSelector('.session-filter', {
      state: 'visible',
      timeout: 10000
    });

    // Check search input exists
    await expect(page.locator('.search-input')).toBeVisible();

    // Check sort dropdown exists
    await expect(page.locator('.sort-select')).toBeVisible();

    // Check date range picker exists
    await expect(page.locator('.date-picker-toggle')).toBeVisible();
  });

  test('should load session details when clicking a card', async ({ page }) => {
    // Wait for sessions to load
    await page.waitForSelector('.session-card', {
      state: 'visible',
      timeout: 10000
    });

    // Click the first session card
    const firstCard = page.locator('.session-card').first();
    await firstCard.click();

    // Wait for session details to load
    await page.waitForSelector('.message-timeline', {
      state: 'visible',
      timeout: 10000
    });

    // Should show statistics
    await expect(page.locator('.statistics-dashboard')).toBeVisible();
  });

  test('should filter sessions by date range', async ({ page }) => {
    // Wait for sessions to load
    await page.waitForSelector('.session-card', {
      state: 'visible',
      timeout: 10000
    });

    // Get initial session count
    const initialCount = await page.locator('.session-card').count();

    // Open date range picker
    await page.click('.date-picker-toggle');

    // Wait for dropdown
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Click "Last 7 days" quick filter
    await page.click('text=Last 7 days');

    // Wait for API to respond
    await page.waitForTimeout(1000);

    // Get filtered count
    const filteredCount = await page.locator('.session-card').count();

    // Should have filtered results (could be less or equal)
    expect(filteredCount).toBeLessThanOrEqual(initialCount);

    // Date picker toggle should show "Filtered" badge
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();

    console.log(`✅ Filtered from ${initialCount} to ${filteredCount} sessions`);
  });

  test('should display readable session card format', async ({ page }) => {
    // Wait for sessions to load
    await page.waitForSelector('.session-card', {
      state: 'visible',
      timeout: 10000
    });

    // Get first session card title
    const firstCardTitle = await page.locator('.session-card__title').first().textContent();

    // Should contain bullet separator (project • branch • time format)
    expect(firstCardTitle).toMatch(/•/);

    console.log(`✅ Session card format: ${firstCardTitle}`);
  });

  test('should handle API errors gracefully', async ({ page }) => {
    // Intercept API and return error
    await page.route('**/api/sessions', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    await page.goto('/');

    // Should show error state
    await page.waitForSelector('.error-container', {
      state: 'visible',
      timeout: 10000
    });

    const errorText = await page.locator('.error-message').textContent();
    expect(errorText).toContain('error');
  });

  test('should handle empty sessions gracefully', async ({ page }) => {
    // Intercept API and return empty list
    await page.route('**/api/sessions', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          sessions: [],
          count: 0,
          page: 1,
          page_size: 50,
          total_pages: 0,
        }),
      });
    });

    await page.goto('/');

    // Should show empty state
    await page.waitForSelector('.empty-container', {
      state: 'visible',
      timeout: 10000
    });

    const emptyText = await page.locator('.empty-container').textContent();
    expect(emptyText).toContain('No sessions available');
  });
});

test.describe('API Health Check', () => {
  test('backend API should be accessible', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/sessions');

    expect(response.status()).toBe(200);

    const data = await response.json();
    expect(data).toHaveProperty('sessions');
    expect(data).toHaveProperty('count');
    expect(Array.isArray(data.sessions)).toBe(true);

    console.log(`✅ API returned ${data.count} sessions`);
  });

  test('backend API should support date filtering', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/sessions?start_date=2026-02-01&end_date=2026-02-25');

    expect(response.status()).toBe(200);

    const data = await response.json();
    expect(data).toHaveProperty('sessions');
    expect(Array.isArray(data.sessions)).toBe(true);

    console.log(`✅ Date filtering returned ${data.count} sessions`);
  });

  test('backend API should reject invalid dates', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/sessions?start_date=invalid-date');

    expect(response.status()).toBe(400);

    const data = await response.json();
    expect(data).toHaveProperty('detail');
    expect(data.detail).toContain('date');
  });
});

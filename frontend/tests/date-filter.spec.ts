/**
 * E2E tests for DateRangePicker component
 *
 * Tests cover:
 * - Opening and closing the date picker dropdown
 * - Quick filter buttons (Last 7/30/90 days)
 * - Custom date range inputs
 * - Clearing date filters
 * - Clicking outside to close dropdown
 * - Filtered state visual indicator
 */

import { test, expect } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@full DateRangePicker', () => {
  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 5000 });
    await page.waitForSelector('.session-card', { state: 'visible' });
  });

  test('should display date picker toggle button', async ({ page }) => {
    const toggle = page.locator('.date-picker-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).toContainText('Date Range');
  });

  test('should open dropdown when clicking toggle', async ({ page }) => {
    // Dropdown should not be visible initially
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Click toggle to open
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Verify dropdown content
    await expect(page.locator('.date-picker-dropdown')).toBeVisible();
    await expect(page.locator('.date-picker-header h4')).toContainText('Filter by Date Range');
  });

  test('should close dropdown when clicking toggle again', async ({ page }) => {
    // Open dropdown
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Click toggle again to close
    await page.click('.date-picker-toggle');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
  });

  test('should display quick filter buttons', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    const quickButtons = page.locator('.quick-filter-button');
    await expect(quickButtons).toHaveCount(3);
    await expect(quickButtons.nth(0)).toContainText('Last 7 days');
    await expect(quickButtons.nth(1)).toContainText('Last 30 days');
    await expect(quickButtons.nth(2)).toContainText('Last 90 days');
  });

  test('should apply Last 7 days quick filter and close dropdown', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Click "Last 7 days"
    await page.click('button:has-text("Last 7 days")');

    // Dropdown should close after quick filter selection
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Toggle should show filtered state
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();

    // Button text should show date range
    const toggleText = await page.locator('.date-picker-toggle').textContent();
    expect(toggleText).toContain('From:');
    expect(toggleText).toContain('To:');
  });

  test('should apply Last 30 days quick filter', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    await page.click('button:has-text("Last 30 days")');

    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
  });

  test('should apply Last 90 days quick filter', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    await page.click('button:has-text("Last 90 days")');

    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
  });

  test('should set custom start date', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Fill in the start date input
    const startInput = page.locator('.date-input').first();
    await startInput.fill('2024-01-01');

    // Click Done to close
    await page.click('.picker-action-button--done');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Should show filtered state
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
    const toggleText = await page.locator('.date-picker-toggle').textContent();
    expect(toggleText).toContain('From: 2024-01-01');
  });

  test('should set custom end date', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Fill in the end date input
    const endInput = page.locator('.date-input').nth(1);
    await endInput.fill('2024-12-31');

    // Click Done
    await page.click('.picker-action-button--done');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Should show filtered state
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
    const toggleText = await page.locator('.date-picker-toggle').textContent();
    expect(toggleText).toContain('To: 2024-12-31');
  });

  test('should set custom date range with both start and end', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Fill both date inputs
    const startInput = page.locator('.date-input').first();
    const endInput = page.locator('.date-input').nth(1);
    await startInput.fill('2024-01-15');
    await endInput.fill('2024-06-30');

    // Click Done
    await page.click('.picker-action-button--done');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Verify filtered state and displayed range
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
    const toggleText = await page.locator('.date-picker-toggle').textContent();
    expect(toggleText).toContain('From: 2024-01-15');
    expect(toggleText).toContain('To: 2024-06-30');
  });

  test('should clear date filter via Clear button', async ({ page }) => {
    // First apply a filter
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });
    await page.click('button:has-text("Last 7 days")');
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();

    // Open dropdown again and click Clear
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });
    await page.click('.picker-action-button--clear');

    // Dropdown should close
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Filtered state should be removed
    await expect(page.locator('.date-picker-toggle--filtered')).not.toBeVisible();

    // Button text should reset
    const toggleText = await page.locator('.date-picker-toggle').textContent();
    expect(toggleText).toContain('Date Range');
    expect(toggleText).not.toContain('From:');
  });

  test('should close dropdown when clicking outside', async ({ page }) => {
    // Open dropdown
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Click outside the dropdown (on the page body / session browser area)
    await page.locator('h1').click();
    await page.waitForTimeout(300);

    // Dropdown should be closed
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
  });

  test('should close dropdown when clicking Done button', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    await page.click('.picker-action-button--done');

    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
  });

  test('should show custom range section with labeled inputs', async ({ page }) => {
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Verify custom range section
    await expect(page.locator('.custom-range h5')).toContainText('Custom Range');

    // Verify labeled date inputs
    const labels = page.locator('.date-label-text');
    await expect(labels.nth(0)).toContainText('From:');
    await expect(labels.nth(1)).toContainText('To:');

    // Verify date inputs are empty by default
    const startInput = page.locator('.date-input').first();
    const endInput = page.locator('.date-input').nth(1);
    await expect(startInput).toHaveValue('');
    await expect(endInput).toHaveValue('');
  });

  test('should persist filter state after closing and reopening dropdown', async ({ page }) => {
    // Apply a quick filter
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });
    await page.click('button:has-text("Last 7 days")');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();

    // Reopen dropdown and verify inputs are populated
    await page.click('.date-picker-toggle');
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    const startInput = page.locator('.date-input').first();
    const endInput = page.locator('.date-input').nth(1);
    await expect(startInput).not.toHaveValue('');
    await expect(endInput).not.toHaveValue('');
  });
});

test.describe('@full DateRangePicker - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } });

  test.beforeEach(async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-card', { timeout: 5000 });
  });

  test('should display and operate date picker on mobile', async ({ page }) => {
    const toggle = page.locator('.date-picker-toggle');
    await expect(toggle).toBeVisible();

    // Open dropdown
    await toggle.click();
    await page.waitForSelector('.date-picker-dropdown', { state: 'visible' });

    // Apply quick filter
    await page.click('button:has-text("Last 7 days")');
    await expect(page.locator('.date-picker-dropdown')).not.toBeVisible();
    await expect(page.locator('.date-picker-toggle--filtered')).toBeVisible();
  });
});

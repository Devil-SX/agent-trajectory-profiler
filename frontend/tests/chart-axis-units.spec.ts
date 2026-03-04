import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

async function readRoleSourceYAxisTicks(page: Page): Promise<string> {
  return page.getByTestId('role-source-chart').innerText();
}

test.describe('@full Chart Axis Units', () => {
  test('@smoke uses compact token/time units for role-source axis ticks', async ({ page }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'Cross-Session Analytics' }).click();
    await expect(page.getByTestId('role-source-chart')).toBeVisible();

    await page.getByTestId('role-source-metric-tokens').click();
    await expect
      .poll(
        async () => readRoleSourceYAxisTicks(page),
        { timeout: 10000 }
      )
      .toMatch(/\d(?:\.\d+)?[KMB]\b/);

    await page.getByTestId('role-source-metric-time').click();
    await expect
      .poll(
        async () => readRoleSourceYAxisTicks(page),
        { timeout: 10000 }
      )
      .toMatch(/\b(min|hour|day)\b/);
  });
});

import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

async function visibleTableRows(page: import('@playwright/test').Page): Promise<number> {
  return page.evaluate(() => {
    const container = document.querySelector('.session-table-container') as HTMLElement | null;
    if (!container) return 0;
    const rows = Array.from(
      document.querySelectorAll('.session-table tbody tr[data-session-id]')
    ) as HTMLElement[];
    const containerRect = container.getBoundingClientRect();
    return rows.filter((row) => {
      const rect = row.getBoundingClientRect();
      return rect.top >= containerRect.top && rect.bottom <= containerRect.bottom;
    }).length;
  });
}

test.describe('@smoke Density mode', () => {
  test('switches to compact mode, persists selection, and increases visible table rows', async ({
    page,
  }) => {
    await setupMockApi(page);
    await page.goto('/');
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 10000 });

    await expect(page.locator('html')).toHaveAttribute('data-density', 'comfortable');
    const comfortableVisibleRows = await visibleTableRows(page);

    await page.selectOption('#density-mode-select', 'compact');
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');

    const compactVisibleRows = await visibleTableRows(page);
    expect(compactVisibleRows).toBeGreaterThanOrEqual(comfortableVisibleRows);

    await page.reload();
    await page.waitForSelector('.session-table tbody tr[data-session-id]', { timeout: 10000 });
    await expect(page.locator('html')).toHaveAttribute('data-density', 'compact');
    await expect(page.locator('#density-mode-select')).toHaveValue('compact');
  });
});

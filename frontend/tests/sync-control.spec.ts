import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('Sync Control', () => {
  test('@smoke should render sync status summary and trigger sync action', async ({ page }) => {
    let syncCallCount = 0;
    await setupMockApi(page);

    await page.route(/\/api\/sync\/run(?:\?.*)?$/, async (route) => {
      syncCallCount += 1;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'completed',
          trigger: 'manual',
          started_at: '2026-02-27T02:00:00.000Z',
          finished_at: '2026-02-27T02:00:03.000Z',
          parsed: 2,
          skipped: 5,
          errors: 0,
          total_files_scanned: 7,
          total_file_size_bytes: 4096,
          ecosystems: [
            {
              ecosystem: 'claude_code',
              files_scanned: 4,
              file_size_bytes: 3072,
              parsed: 2,
              skipped: 2,
              errors: 0,
            },
            {
              ecosystem: 'codex',
              files_scanned: 3,
              file_size_bytes: 1024,
              parsed: 0,
              skipped: 3,
              errors: 0,
            },
          ],
          error_samples: [],
        }),
      });
    });

    await page.goto('/');

    const syncControl = page.locator('.sync-control');
    await expect(syncControl).toBeVisible();
    await expect(syncControl).toContainText('DB Sync');
    await expect(syncControl).toContainText('Parsed:');
    await expect(syncControl).toContainText('Skipped:');
    await expect(syncControl).toContainText('Errors:');
    await expect(syncControl).toContainText('Claude Code');
    await expect(syncControl).toContainText('Codex');

    await page.getByRole('button', { name: 'Sync Now' }).click();
    await expect.poll(() => syncCallCount).toBe(1);
  });
});

import { expect, test } from '@playwright/test';
import { setupMockApi } from './fixtures/mockServer';

test.describe('@smoke API base URL host alignment', () => {
  test('uses same hostname for backend target when frontend opens on 127.0.0.1', async ({ page }) => {
    await setupMockApi(page);

    const sessionsRequestPromise = page.waitForRequest((request) =>
      request.url().includes('/api/sessions?page=1&page_size=200&view=logical')
    );

    await page.goto('http://127.0.0.1:5173');
    await page.waitForSelector('.session-browser:not(.loading)', { timeout: 10000 });

    const sessionsRequest = await sessionsRequestPromise;
    expect(sessionsRequest.url()).toContain('127.0.0.1:8000/api/sessions');
  });
});

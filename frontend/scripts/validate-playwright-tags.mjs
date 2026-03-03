import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

const TEST_DIR = join(process.cwd(), 'tests');
const ALLOWED_TAG_RE = /@(smoke|full|visual|a11y|manual)\b/;

const files = readdirSync(TEST_DIR)
  .filter((entry) => entry.endsWith('.spec.ts'))
  .sort();

const failures = [];

for (const file of files) {
  const fullPath = join(TEST_DIR, file);
  const content = readFileSync(fullPath, 'utf-8');

  if (!ALLOWED_TAG_RE.test(content)) {
    failures.push(
      `${file}: missing test tier tag. Add at least one of @smoke/@full/@visual/@a11y/@manual.`
    );
  }
}

if (failures.length > 0) {
  console.error('Playwright tag contract failed:\n');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Playwright tag contract passed for ${files.length} spec files.`);

import { execSync } from 'node:child_process';

const checkMode = process.argv.includes('--check');
const openapiPath = 'src/types/generated/openapi.json';
const generatedTypePath = 'src/types/generated/api.generated.ts';

function run(cmd) {
  execSync(cmd, { stdio: 'inherit' });
}

run(`uv run python ../scripts/export_openapi_schema.py ${openapiPath}`);
run(`openapi-typescript ${openapiPath} --output ${generatedTypePath}`);

if (checkMode) {
  try {
    run(`git diff --exit-code -- ${openapiPath} ${generatedTypePath}`);
  } catch {
    console.error(
      [
        'Generated API contracts are stale.',
        'Run `npm --prefix frontend run typegen` and commit updated generated files.',
      ].join('\n')
    );
    process.exit(1);
  }
}

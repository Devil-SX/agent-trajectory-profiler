// Fixture-only browser acceptance. Run remotely with an explicitly supplied candidate HTML.
// No production URL, credentials, persistent database or model requests are used.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('node:fs');
const http = require('node:http');
const assert = require('node:assert/strict');
const html = fs.readFileSync(process.argv[2], 'utf8');
const output = process.argv[3];
assert(output, 'Provide an isolated output directory');
assert(!html.includes('\u00b7'), 'Website source contains a forbidden middle dot');
fs.mkdirSync(output, {recursive: true});

const metric = input => ({input, output: input === null ? null : input / 10,
  recorded_tokens: input, cached: 0, cache_write: null, calls: 1,
  known_subtotal_usd: input === null ? null : input / 10000,
  cost_status: input === null ? 'unknown' : 'partial', unpriced_calls: 1,
  active_seconds_estimate: input === null ? null : input / 10,
  human_interactions: 2, human_input_chars: 35,
  unknown_origin_interactions: 0, missing_human_input_chars: 0});
const childMetrics = {...metric(250), human_interactions: null, human_input_chars: null,
  unknown_origin_interactions: 2, missing_human_input_chars: 2};
const sessions = [
  {id: 'cpm', native_session_id: 'native-cpm', display_title: 'AI CPM 优化验证',
    cwd: '/research/embodied/ai-cpm', project: 'embodied', project_name: '具身智能',
    started_at: '2026-10-02T06:00:00Z', last_activity_at: '2026-10-20T07:00:00Z',
    analysis_status: 'complete', has_analysis: true, agent: 'Codex', metrics: metric(1000)},
  {id: 'other', native_session_id: 'native-other', display_title: '另一会话及未知开销',
    cwd: '/work/BatCave', project: 'batcave', project_name: 'BatCave',
    started_at: '2026-10-12T06:00:00Z', last_activity_at: '2026-10-19T07:00:00Z',
    analysis_status: 'complete', has_analysis: true, agent: 'Pi',
    metrics: {...metric(null), human_interactions: null, human_input_chars: null,
      unknown_origin_interactions: 1, missing_human_input_chars: 1}},
];
const tasks = [
  {id: 'root', parent_id: null, title: '验证 AI CPM', metrics: metric(1000),
    segments: [{start_operation_id: '1', end_operation_id: '3'}]},
  {id: 'child', parent_id: 'root', title: '缓存实验及证据核对', metrics: childMetrics,
    segments: [{start_operation_id: '2', end_operation_id: '2'}]},
];
const operations = [1, 2, 3].map(id => ({id: String(id), title: '实验记录 ' + id,
  kind: 'tool', timestamp: '2026-10-20T06:00:00Z', body_available: true,
  source: {source_name: 'fixture.jsonl', line: id}, metrics: metric(id * 10)}));
const overview = {generated_at: '2026-10-20T08:00:00Z', projects: [], daily: [],
  anomalies: [], coverage: {}, pricing: {prices: []}};
let batchState = 'running', listDelay = 0, failList = false, detailFailure = false;
const requests = [], listQueries = [], posts = [], pageErrors = [], checks = [];
const layouts = {};
async function screenshotTop(page, filename) {
  await page.evaluate(() => {window.scrollTo(0, 0);const pane=document.querySelector('#analysis-content');if(pane)pane.scrollTop=0;});
  await page.screenshot({path: output + '/' + filename, fullPage: true});
}
async function layout(page) {
  return page.evaluate(() => ({analysis_context_height:document.querySelector('.analysis-context')?.getBoundingClientRect().height, workspace_toolbar_height:document.querySelector('.workspace-toolbar')?.getBoundingClientRect().height, filter_disclosure_height:document.querySelector('#workspace-filters')?.getBoundingClientRect().height, filters_open:document.querySelector('#workspace-filters')?.open, viewport_width:innerWidth, document_width:document.documentElement.scrollWidth, document_horizontal_overflow:document.documentElement.scrollWidth>innerWidth+1}));
}
const batch = () => ({batch_id: 'fixture-batch', status: batchState, total: 2, concurrency: 4,
  counts: batchState === 'running' ? {running: 1, queued: 1} :
    batchState === 'failed' ? {complete: 1, failed: 1} : {complete: 2},
  items: sessions.map((session, i) => ({session_id: session.id, session,
    status: batchState === 'running' ? (i ? 'queued' : 'running') :
      batchState === 'failed' && i ? 'failed' : 'complete',
    progress: {completed_chunks: i ? 2 : 6, total_chunks: 6, model: 'fixture-glm'},
    resume: batchState === 'failed' && i ?
      {eligible: true, job_id: 'fixture-failed-job', generation: 0, completed_chunks: 2} : null}))});
function selectedSessions(params) {
  // Filtering and sorting happen BEFORE pagination. Deliberately return one row per page,
  // including for the advertised limit=100, so filter ownership is observable.
  const q = (params.get('q') || '').toLowerCase();
  const project = params.get('project'), cwd = params.get('cwd'), status = params.get('analysis_status');
  let rows = sessions.filter(s => (!project || s.project === project) &&
    (!cwd || s.cwd === cwd || s.cwd.startsWith(cwd.replace(/\/$/, '') + '/')) &&
    (!status || status === 'all' || status === 'analyzed' && s.has_analysis || status === s.analysis_status) &&
    (!params.get('since') || s.started_at.slice(0, 10) >= params.get('since')) &&
    (!params.get('until') || s.started_at.slice(0, 10) <= params.get('until')) &&
    (!q || [s.id, s.native_session_id, s.display_title, s.cwd].join(' ').toLowerCase().includes(q)));
  const sort = params.get('sort');
  rows.sort((a, b) => String(sort === 'started_desc' ? b.started_at : b.last_activity_at)
    .localeCompare(String(sort === 'started_desc' ? a.started_at : a.last_activity_at)));
  const offset = Number(params.get('cursor') || 0);
  return {sessions: rows.slice(offset, offset + 1), next_cursor: offset + 1 < rows.length ? String(offset + 1) : null,
    truncated: offset + 1 < rows.length,
    directories: ['/research/embodied', '/research/embodied/ai-cpm', '/work/BatCave'],
    projects: [{id: 'embodied', name: '具身智能'}, {id: 'batcave', name: 'BatCave'}]};
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://fixture');
  requests.push({path: url.pathname, query: Object.fromEntries(url.searchParams), method: req.method});
  let body = '';
  for await (const chunk of req) body += chunk;
  res.setHeader('content-type', 'application/json');
  if (req.method !== 'GET') {
    posts.push({path: url.pathname, body});
    res.writeHead(405); return res.end(JSON.stringify({error: 'Fixture does not authorize mutations'}));
  }
  if (url.pathname === '/trajectory/api/overview') return res.end(JSON.stringify(overview));
  if (url.pathname === '/api/services.json') return res.end('{"services":[]}');
  if (url.pathname === '/trajectory/api/analysis-batches') return res.end(JSON.stringify({batches: [batch()]}));
  if (url.pathname === '/trajectory/api/analysis-batches/fixture-batch') return res.end(JSON.stringify(batch()));
  if (url.pathname === '/trajectory/api/sessions') {
    listQueries.push(Object.fromEntries(url.searchParams));
    const captured = selectedSessions(url.searchParams), delay = listDelay, failed = failList;
    await new Promise(resolve => setTimeout(resolve, delay));
    if (failed) {res.writeHead(503); return res.end('{}');}
    return res.end(JSON.stringify(captured));
  }
  const match = url.pathname.match(/^\/trajectory\/api\/sessions\/([^/]+)\/analysis$/);
  if (match) {
    if (detailFailure) {res.writeHead(503); return res.end('{}');}
    const session = sessions.find(s => s.id === match[1]);
    return res.end(JSON.stringify({session, status: 'complete', has_analysis: true,
      source_revision: 'fixture-revision', analysis_revision: 1, coverage: {content_available: true},
      tasks: session.id === 'cpm' ? tasks : [{id: 'unknown-root', title: '无法计价的任务',
        parent_id: null, metrics: session.metrics, segments: []}],
      operations: session.id === 'cpm' ? operations : [],
      provenance: {model: 'fixture-glm', backend: 'jindu', reasoning_effort: 'high', cost: null,
        chunks: 1, analysis_usage: [{chunk: 1, attempt: 1, valid: true,
          elapsed_seconds: 2, usage: {prompt_tokens: 100, completion_tokens: 20}}]}}));
  }
  const operation = url.pathname.match(/^\/trajectory\/api\/sessions\/cpm\/operations\/(\d+)$/);
  if (operation) {
    assert.equal(url.searchParams.get('source_revision'), 'fixture-revision');
    return res.end(JSON.stringify({...operations.find(op => op.id === operation[1]),
      text: '仅展开时读取 <script>window.fixtureLeaked=true</script>'}));
  }
  if (url.pathname.endsWith('.svg')) {
    res.setHeader('content-type', 'image/svg+xml');
    return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"/>');
  }
  res.setHeader('content-type', 'text/html'); res.end(html);
});
const countPath = path => requests.filter(r => r.path === path).length;
const bodyReads = () => requests.filter(r => /\/operations\//.test(r.path)).length;
const listed = page => page.locator('.session-button').evaluateAll(nodes => nodes.map(n => n.dataset.sessionId));
const settleList = page => page.waitForFunction(() => document.querySelector('#session-list')?.getAttribute('aria-busy') === 'false');
async function nextList(page, action) {
  await page.locator('#workspace-filters').evaluate(n => {n.open = false;});
  const response = page.waitForResponse(r => new URL(r.url()).pathname === '/trajectory/api/sessions');
  await action(); await response; await settleList(page);
}
async function toggle(page, id, open) {
  const element = page.locator('#' + id);
  assert.equal(await element.evaluate(n => n.tagName), 'DETAILS');
  if (await element.evaluate(n => n.open) !== open) await element.locator(':scope > summary').click();
  assert.equal(await element.evaluate(n => n.open), open);
  if (['workspace-filters', 'batch-activity'].includes(id)) {
    const field = id === 'workspace-filters' ? 'filters_open' : 'batch_open';
    await page.waitForFunction(({field, open}) => JSON.parse(localStorage.getItem('trajectory-workbench-v1') || '{}')[field] === open, {field, open});
  }
}
async function metricValue(page, key) {
  return (await page.locator('.analysis-summary .card[data-metric="' + key + '"] .value').innerText()).trim();
}
async function contextual(page, scope, id, input, humanUnknown = false) {
  assert.equal(await page.locator('.analysis-summary').getAttribute('data-metric-scope'), scope);
  if (id) assert.equal(await page.locator('.analysis-summary').getAttribute('data-task-id'), id);
  assert.match(await metricValue(page, 'input'), new RegExp(input));
  assert.match(await page.locator('.metric-scope-label').innerText(), scope === 'task' ? /当前任务.*含子任务/ : /会话总计/);
  if (humanUnknown) {
    assert.match(await metricValue(page, 'human_interactions'), /未知/);
    assert.match(await metricValue(page, 'human_input_chars'), /未知/);
  }
}
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = 'http://127.0.0.1:' + server.address().port;
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROMIUM_PATH,
    args: ['--no-sandbox', '--disable-gpu']});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
    // Load only a fixture batch ID, never production browser state.
    await context.addInitScript(() => {
      if (!localStorage.getItem('trajectory-workbench-v1')) localStorage.setItem('trajectory-workbench-v1',
        JSON.stringify({batch_id: 'fixture-batch'}));
    });
    const page = await context.newPage(); page.on('pageerror', e => pageErrors.push(e.message));
    for (const method of ['fill', 'selectOption']) {
      const original = page[method].bind(page);
      page[method] = async (selector, ...args) => {
        if (/^#(?:project|since|until|session-status|session-directory|session-sort)$/.test(selector)) {
          await page.locator(selector).evaluate(n => {const drawer = n.closest('details'); if (drawer) drawer.open = true;});
        }
        return original(selector, ...args);
      };
    }
    await page.goto(origin + '/trajectory/');
    await page.waitForSelector('[data-session-id="cpm"]'); await settleList(page);
    await page.waitForSelector('#batch-activity');
    assert.equal(countPath('/trajectory/api/overview'), 0);
    assert.deepEqual(await listed(page), ['cpm']);
    assert.equal(await page.locator('#session-search').isVisible(), true);
    assert.equal(await page.locator('#workspace-filters').evaluate(n => n.open), false);
    for (const id of ['project', 'since', 'until', 'session-status', 'session-directory', 'session-sort']) {
      assert.equal(await page.locator('#' + id).count(), 1, 'Duplicate filter ' + id);
      assert.equal(await page.locator('#workspace-filters #' + id).count(), 1);
      assert.equal(await page.locator('#' + id).isVisible(), false);
    }
    checks.push('one canonical collapsed filter toolbar; initial task view skips overview');
    let before = requests.length;
    await toggle(page, 'workspace-filters', true);
    await toggle(page, 'workspace-filters', false);
    assert.equal(requests.length, before, 'Opening filters must not request data');
    await toggle(page, 'workspace-filters', true);
    await page.reload(); await page.waitForSelector('[data-session-id="cpm"]');
    assert.equal(await page.locator('#workspace-filters').evaluate(n => n.open), true);
    checks.push('filter drawer toggles without HTTP and persists across reload');
    await nextList(page, () => page.click('#sessions-more'));
    assert.deepEqual(await listed(page), ['cpm', 'other']);
    assert.equal(listQueries.at(-1).cursor, '1');
    await nextList(page, () => page.fill('#session-search', 'native-other'));
    assert.deepEqual(await listed(page), ['other'], 'Server must filter before page slicing');
    assert.equal(listQueries.at(-1).cursor, undefined);
    await nextList(page, () => page.fill('#session-search', ''));
    await nextList(page, () => page.selectOption('#session-directory', '/research/embodied'));
    assert.deepEqual(await listed(page), ['cpm'], 'Server-authorized directory descendants must not be removed by browser equality filtering');
    await nextList(page, () => page.selectOption('#session-directory', ''));
    const beforeCoalesce = listQueries.length;
    await nextList(page, async () => {
      await page.selectOption('#project', 'embodied');
      await page.fill('#since', '2026-10-01'); await page.locator('#since').dispatchEvent('change');
      await page.fill('#until', '2026-10-05'); await page.locator('#until').dispatchEvent('change');
    });
    assert.equal(listQueries.length, beforeCoalesce + 1, 'Scope edits must coalesce');
    assert.deepEqual(await listed(page), ['cpm']);
    assert.equal(listQueries.at(-1).project, 'embodied');
    assert.equal(listQueries.at(-1).since, '2026-10-01'); assert.equal(listQueries.at(-1).until, '2026-10-05');
    for (const id of ['project', 'since', 'until']) assert.equal(await page.locator('#filter-chips [data-filter="' + id + '"]').count(), 1);
    await toggle(page, 'workspace-filters', false);
    await nextList(page, () => page.locator('#filter-chips [data-filter="since"]').click());
    assert.equal(await page.inputValue('#since'), ''); assert.equal(await page.inputValue('#until'), '2026-10-05');
    await nextList(page, () => page.click('#filters-clear'));
    assert.equal(await page.inputValue('#project'), ''); assert.equal(await page.inputValue('#until'), '');
    // Distinct directory, analyzed state and non-default sort persist, with server ownership.
    await nextList(page, async () => {
      await page.selectOption('#session-directory', '/work/BatCave');
      await page.selectOption('#session-status', 'analyzed');
      await page.selectOption('#session-sort', 'started_desc');
      await page.fill('#session-search', 'native-other');
    });
    assert.deepEqual(await listed(page), ['other']);
    assert.equal(listQueries.at(-1).cwd, '/work/BatCave');
    assert.equal(listQueries.at(-1).analysis_status, 'analyzed'); assert.equal(listQueries.at(-1).sort, 'started_desc');
    await page.reload(); await page.waitForSelector('[data-session-id="other"]'); await settleList(page);
    for (const [id, value] of [['session-directory', '/work/BatCave'], ['session-status', 'analyzed'],
      ['session-sort', 'started_desc'], ['session-search', 'native-other']]) assert.equal(await page.inputValue('#' + id), value);
    checks.push('server filtering before cursor pagination; coalesced scope; single chips; clearing; all filter persistence');
    await nextList(page, () => page.click('#filters-clear'));
    // An obsolete slow scope response must never overwrite a newer query.
    listDelay = 650;
    const oldResponse = page.waitForResponse(r => new URL(r.url()).searchParams.get('q') === 'native-cpm');
    await page.fill('#session-search', 'native-cpm');
    await page.waitForRequest(r => new URL(r.url()).searchParams.get('q') === 'native-cpm');
    listDelay = 0; await page.fill('#session-search', 'native-other'); await oldResponse;
    await page.waitForFunction(() => document.querySelector('.session-button')?.dataset.sessionId === 'other');
    await settleList(page); assert.deepEqual(await listed(page), ['other']);
    checks.push('late filtered response cannot replace the current server scope');
    await nextList(page, () => page.fill('#session-search', 'native-cpm'));
    await page.click('[data-session-id="cpm"]'); await page.waitForSelector('.analysis-context');
    await contextual(page, 'session', null, '1[,.]?000');
    const sessionMetricValues = await page.locator('.analysis-summary .card').evaluateAll(ns => Object.fromEntries(ns.map(n => [n.dataset.metric,n.querySelector('.value').textContent])));
    assert.equal(await page.locator('.analysis-context').evaluate(n => getComputedStyle(n).position), 'sticky');
    assert.equal(await page.locator('.analysis-title').innerText(), 'AI CPM 优化验证');
    assert.equal(bodyReads(), 0);
    const analysisBefore = countPath('/trajectory/api/sessions/cpm/analysis');
    await page.locator('.task-select[data-task-id="child"]').first().click();
    await contextual(page, 'task', 'child', '250', true);
    const childMetricValues = await page.locator('.analysis-summary .card').evaluateAll(ns => Object.fromEntries(ns.map(n => [n.dataset.metric,n.querySelector('.value').textContent])));
    for (const key of ['input','output','known_subtotal_usd','active_seconds_estimate','human_interactions','human_input_chars']) assert.notEqual(childMetricValues[key],sessionMetricValues[key], 'Selected child must update metric '+key);
    assert.match(childMetricValues.output,/25/);
    assert.match(await page.locator('.task-context-title').innerText(), /缓存实验/);
    assert.match(await metricValue(page, 'known_subtotal_usd'), /已知小计|部分计价/);
    for (const label of ['分段时间线', '开销火焰图', '任务层级']) {
      await page.getByRole('button', {name: label, exact: true}).click();
      assert.equal(await page.getByRole('button', {name: label, exact: true}).getAttribute('aria-pressed'), 'true');
      await contextual(page, 'task', 'child', '250', true);
    }
    assert.equal(countPath('/trajectory/api/sessions/cpm/analysis'), analysisBefore);
    assert.equal(bodyReads(), 0);
    await toggle(page, 'metric-details', true);
    assert.match(await page.locator('#metric-details').innerText(), /缓存写入/);
    assert.match(await page.locator('#metric-details').innerText(), /未知/);
    const cachedRow = page.locator('#metric-details tr').filter({hasText: '缓存读取'});
    assert.match(await cachedRow.innerText(), /(?:^|\s)0(?:\s|$)/, 'Recorded zero remains distinct from unknown cache writes');
    await page.getByRole('button', {name: '查看会话总计', exact: true}).click();
    await contextual(page, 'session', null, '1[,.]?000');
    await page.getByRole('button', {name: '分段时间线', exact: true}).click();
    await page.locator('.timeline-segment[aria-label^="缓存实验"]').click();
    await contextual(page, 'task', 'child', '250', true);
    await page.getByRole('button', {name: '开销火焰图', exact: true}).click();
    await page.locator('.flame-frame[title^="验证 AI CPM"]').click();
    await contextual(page, 'task', 'root', '1[,.]?000');
    checks.push('selected task title and six contextual metrics survive all three views; timeline and flame selection; parent includes children');
    const evidencePanel = page.locator('#evidence-panel');
    if (await evidencePanel.count()) await toggle(page, 'evidence-panel', true);
    const evidence = page.locator('#analysis-evidence');
    assert.equal(bodyReads(), 0);
    await evidence.locator('summary').first().click();
    await page.waitForFunction(() => document.querySelector('#analysis-evidence .operation-body pre')?.textContent.includes('<script>'));
    assert.equal(bodyReads(), 1); assert.equal(await page.evaluate(() => window.fixtureLeaked), undefined);
    await page.getByText('本次分析调用与开销', {exact: true}).click();
    assert.match(await page.locator('#analysis-content').innerText(), /jindu/);
    checks.push('operation body remains lazy, revision-pinned and escaped; analysis call cost stays accessible');
    // Batch compact activity states must all be discoverable without expanding a large panel.
    for (const state of ['running', 'failed', 'complete']) {
      batchState = state;
      if (state !== 'running') {await page.reload(); await page.waitForSelector('#batch-activity'); await settleList(page);}
      const panel = page.locator('#batch-activity');
      assert.equal(await panel.evaluate(n => n.open), false);
      assert.equal(await panel.locator(':scope > summary').getAttribute('data-state'), state);
      assert.match(await panel.locator(':scope > summary').innerText(), /后台分析/);
      before = requests.length;
      await toggle(page, 'batch-activity', true); assert.equal(requests.length, before);
      assert.match(await panel.innerText(), /AI CPM 优化验证/);
      assert.match(await panel.innerText(), /\/research\/embodied\/ai-cpm/);
      if (state === 'failed') assert.equal(await panel.locator('[data-resume-job="fixture-failed-job"]').isVisible(), true);
      await page.locator('#batch-activity > summary').focus(); await page.keyboard.press('Escape');
      assert.equal(await panel.evaluate(n => n.open), false);
      await toggle(page, 'batch-activity', true); await page.locator('h1').click();
      assert.equal(await panel.evaluate(n => n.open), false);
      await page.waitForFunction(() => JSON.parse(localStorage.getItem('trajectory-workbench-v1') || '{}').batch_open === false);
    }
    await toggle(page, 'batch-activity', true); await page.reload(); await page.waitForSelector('#batch-activity');
    assert.equal(await page.locator('#batch-activity').evaluate(n => n.open), true);
    await toggle(page, 'batch-activity', false);
    checks.push('compact running, failed and complete activity; failure resume visible but never executed; Escape/outside close; reload persistence');
    await page.click('[data-session-id="cpm"]'); await page.waitForSelector('.analysis-context');
    await page.getByRole('button', {name: '任务层级', exact: true}).click();
    await page.locator('.task-select[data-task-id="child"]').first().click();
    await contextual(page, 'task', 'child', '250', true);
    layouts.desktop = await layout(page);
    await screenshotTop(page, 'compact-workbench-desktop.png');
    await page.setViewportSize({width: 390, height: 844});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await toggle(page, 'workspace-filters', true);
    await page.locator('#workspace-filters > summary').focus();
    await page.keyboard.press('Enter'); assert.equal(await page.locator('#workspace-filters').evaluate(n => n.open), false);
    await page.keyboard.press('Enter'); assert.equal(await page.locator('#workspace-filters').evaluate(n => n.open), true);
    assert.equal(await page.locator('#workspace-filters > summary').evaluate(n => document.activeElement === n), true);
    await screenshotTop(page, 'compact-workbench-mobile-filters.png');
    await toggle(page, 'workspace-filters', false);
    await page.emulateMedia({reducedMotion: 'reduce'});
    listDelay = 600;
    const refreshed = page.waitForResponse(r => new URL(r.url()).pathname === '/trajectory/api/sessions');
    await page.click('#sessions-refresh');
    await refreshed; await settleList(page); listDelay = 0;
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    layouts.mobile = await layout(page);
    await screenshotTop(page, 'compact-workbench-mobile.png');
    const motionContext = await browser.newContext({viewport: {width: 390, height: 844}, reducedMotion: 'reduce'});
    const motionPage = await motionContext.newPage();
    motionPage.on('pageerror', e => pageErrors.push(e.message));
    listDelay = 650; await motionPage.goto(origin + '/trajectory/');
    await motionPage.waitForSelector('#session-list .loading-orbit');
    assert.equal(await motionPage.locator('#session-list .loading-orbit').evaluate(n => getComputedStyle(n).animationName), 'none');
    await motionPage.screenshot({path: output + '/compact-workbench-mobile-reduced-motion-loading.png', fullPage: true});
    await settleList(motionPage); listDelay = 0; await motionContext.close();
    checks.push('desktop and 390px mobile screenshots; native keyboard disclosure; reduced-motion animation disabled; no document horizontal overflow');
    await nextList(page, () => page.fill('#session-search', 'native-other'));
    await page.click('[data-session-id="other"]'); await page.waitForSelector('.analysis-context');
    await contextual(page, 'session', null, '未知', true);
    assert.match(await metricValue(page, 'known_subtotal_usd'), /未知/);
    assert(!/^0(?:[.,]0+)?$/.test(await metricValue(page, 'human_input_chars')));
    failList = true; await nextList(page, () => page.click('#sessions-refresh'));
    assert.match(await page.locator('#sessions-state').innerText(), /保留上次/);
    assert.deepEqual(await listed(page), ['other']); failList = false;
    detailFailure = true; await page.click('[data-session-id="other"]');
    await page.waitForFunction(() => document.querySelector('#analysis-content')?.textContent.includes('503'));
    detailFailure = false; await page.getByRole('button', {name: '重新读取', exact: true}).click();
    await page.waitForSelector('.analysis-context'); await contextual(page, 'session', null, '未知', true);
    checks.push('unknown human and price values remain unknown; failed list keeps data; failed detail retries without a paid action');
    assert.equal(posts.length, 0); assert.deepEqual(pageErrors, []);
    const result = {result: 'passed', fixture_only: true, candidate_html: process.argv[2], checks,
      candidate_html_sha256: require('node:crypto').createHash('sha256').update(html).digest('hex'), layouts, requests: requests.length, listing_requests: listQueries.length, operation_body_requests: bodyReads(),
      mutation_requests: posts.length, page_errors: pageErrors, listing_queries: listQueries};
    fs.writeFileSync(output + '/result.json', JSON.stringify(result, null, 2)); console.log(JSON.stringify(result));
    await context.close();
  } finally {await browser.close(); await new Promise(resolve => server.close(resolve));}
})().catch(error => {console.error(error); process.exitCode = 1; server.close();});

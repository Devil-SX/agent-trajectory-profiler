// Filter inputs live in one native disclosure; reopen it before each scoped edit.
const openFilters = async page => {if(await page.locator('#batch-activity').count()&&await page.locator('#batch-activity').evaluate(n=>n.open)){await page.keyboard.press('Escape');assert.equal(await page.locator('#batch-activity').evaluate(n=>n.open),false);}if(!await page.locator('#workspace-filters').evaluate(n=>n.open))await page.locator('#workspace-filters > summary').click();await page.locator('#session-status').waitFor({state:'visible'});};
const editFilter = async (page, method, ...args) => {await openFilters(page);await page[method](...args);if(await page.locator('#workspace-filters').evaluate(n=>n.open))await page.locator('#workspace-filters > summary').click();};
const analysisText = async page => {await page.locator('.analysis-context-details').evaluateAll(ns=>ns.forEach(n=>{n.open=true;}));return page.locator('#analysis-content').innerText();};
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),http=require('http'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
assert(!html.includes('\u00b7'));
const sessions=[
 {id:'complete',native_session_id:'native-cpm-7f12',title:'rollout-cpm-source-file.jsonl',display_title:'分析 CPM 优化',cwd:'/research/embodied',started_at:'2026-10-01T06:00:00Z',last_activity_at:'2026-10-18T07:00:00Z',has_analysis:true,analysis_status:'complete',agent:'Codex',summary:'已有摘要，不新增模型请求'},
 {id:'metadata',display_title:'仅元信息部分上传',cwd:'/research/embodied',started_at:'2026-10-10T06:00:00Z',last_activity_at:'2026-10-19T06:00:00Z',has_analysis:false,analysis_status:'partial'},
 {id:'child',display_title:'子 Agent 验证稀疏矩阵',cwd:'/research/embodied',started_at:'2026-10-12T06:00:00Z',last_activity_at:'2026-10-18T08:00:00Z',has_analysis:true,analysis_status:'stale',parent_session_id:'complete'},
 {id:'pending',display_title:'新的 CPM 对照实验',cwd:'/research/embodied',started_at:'2026-10-17T06:00:00Z',last_activity_at:'2026-10-17T06:00:00Z',has_analysis:false,analysis_status:'not_started'},
 {id:'failed',display_title:'失败的工作流',cwd:'/work/BatCave',last_activity_at:'2026-10-16T06:00:00Z',has_analysis:false,analysis_status:'failed'},
 {id:'running',display_title:'正在分类',cwd:'/work/BatCave',last_activity_at:'2026-10-15T06:00:00Z',has_analysis:false,analysis_status:'running'}
];
let posts=[],batchReads=0,failSubmit=true,failList=false,childQueued=false,childReanalysisStatus='queued',pendingSnapshot=false,childHistorical=true;const analysisPosts=[];let childAnalysisReads=0;
const queries=[];
const detachedSession={id:'outside-list',display_title:'验证 CPM 编译器融合策略',cwd:'/research/embodied/ai-cpm',started_at:'2026-10-10T06:00:00Z',last_activity_at:'2026-10-19T07:30:00Z'};
const batch={batch_id:'batch-test',status:'running',total:2,concurrency:4,counts:{running:1,queued:1},items:[{session_id:'metadata',status:'running',progress:{completed_chunks:3,total_chunks:12,model:'glm-test'},elapsed_seconds:22},{session_id:'outside-list',status:'queued',session:detachedSession}]};
const server=http.createServer(async(req,res)=>{
 let body='';for await(const chunk of req)body+=chunk;
 res.setHeader('content-type','application/json');
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/trajectory/api/overview')return res.end(JSON.stringify({generated_at:'2026-10-19T06:00:00Z',projects:[],daily:[],anomalies:[],coverage:{},pricing:{prices:[]}}));
 if(url.pathname==='/api/services.json')return res.end(JSON.stringify({services:[]}));
 if(url.pathname==='/trajectory/api/sessions'){
  queries.push(Object.fromEntries(url.searchParams));
  if(failList){res.writeHead(503);return res.end('{}')}
  const query=(url.searchParams.get('q')||'').toLowerCase();const scope=Object.fromEntries(url.searchParams),filtered=sessions.filter(s=>{
   const status=s.analysis_status||'not_started',matches=scope.analysis_status==='analyzed'?s.has_analysis:scope.analysis_status==='busy'?['queued','running'].includes(status):scope.analysis_status==='not_started'?!s.has_analysis&&!['queued','running','failed'].includes(status):scope.analysis_status==='failed'?status==='failed':true;
   return matches&&(!scope.cwd||s.cwd===scope.cwd||s.cwd?.startsWith(scope.cwd+'/'))&&(!scope.project||s.project===scope.project)&&(!scope.since||(s.last_activity_at||s.started_at||'').slice(0,10)>=scope.since)&&(!scope.until||(s.last_activity_at||s.started_at||'').slice(0,10)<=scope.until)&&['id','title','display_title','cwd','first_user_message','summary','native_session_id','agent_path','parent_session_id','agent','project','project_name'].map(k=>s[k]||'').join(' ').toLowerCase().includes(query)
  }).sort((a,b)=>(scope.sort==='directory'?(a.cwd||'').localeCompare(b.cwd||''):0)||(Date.parse(scope.sort==='started_desc'?b.started_at:b.last_activity_at||b.started_at)||0)-(Date.parse(scope.sort==='started_desc'?a.started_at:a.last_activity_at||a.started_at)||0)||a.id.localeCompare(b.id));return res.end(JSON.stringify({sessions:filtered,directories:['/research/embodied','/work/BatCave']}));
 }
 if(url.pathname==='/trajectory/api/analysis-batches'&&req.method==='POST'){
  posts.push(JSON.parse(body));
  if(failSubmit){res.writeHead(503);return res.end('{}')}
  return res.end(JSON.stringify(batch));
 }
 if(url.pathname==='/trajectory/api/analysis-batches')return res.end(JSON.stringify({batches:[]}));
 if(url.pathname==='/trajectory/api/analysis-batches/batch-test'){batchReads++;return res.end(JSON.stringify(batch))}
 const match=url.pathname.match(/\/sessions\/([^/]+)\/analysis$/);
 if(match){if(match[1]==='child'&&req.method==='GET')childAnalysisReads++;if(match[1]==='child'&&req.method==='POST'){analysisPosts.push(JSON.parse(body));childQueued=true;return res.end(JSON.stringify({status:'queued'}))}const session=sessions.find(s=>s.id===match[1]);return res.end(JSON.stringify({session,source_pending:pendingSnapshot&&session.id==='complete',historical_snapshot:session.id==='child'&&childHistorical,analysis_snapshot_available:session.id==='child'&&childHistorical,analysis_matches_parsed:true,has_analysis:session.has_analysis,status:session.id==='child'&&childQueued&&!childHistorical?'queued':session.analysis_status,reanalysis:session.id==='child'&&childQueued&&childHistorical?{status:childReanalysisStatus,source_revision:'queued-revision',progress:{}}:null,resume:session.id==='child'&&childReanalysisStatus==='failed'?{eligible:true,job_id:'job-child',generation:0,completed_chunks:2}:null,coverage:{content_available:true,warnings:session.analysis_status==='stale'?['源记录已更新，旧分析未绑定当前证据']:[]},analysis_current:session.analysis_status!=='stale',analysis_cost:session.id==='complete'?{cost_status:'partial',known_subtotal_usd:0.123,calls:[{price:{source_url:'https://docs.z.ai/guides/overview/pricing',verified_at:'2026-10-19T04:00:00Z'}}]}:null,provenance:{model:'glm-test',reasoning_effort:'high',backend:'jindu',cost:null,chunks:2,analysis_usage:[{chunk:1,attempt:1,elapsed_seconds:1.2,valid:true,usage:{prompt_tokens:100,completion_tokens:20}}]},tasks:session.has_analysis&&(session.analysis_status!=='stale'||childHistorical)?[{id:'root',title:'优化 CPM',metrics:{input:100,known_subtotal_usd:0.1,cost_status:'complete'},segments:[]}]:[],operations:[]}))}
 if(req.url.endsWith('.svg')){res.setHeader('content-type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg"/>')}
 res.setHeader('content-type','text/html');res.end(html);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 const url='http://127.0.0.1:'+server.address().port+'/trajectory/';
 await page.goto(url);await page.waitForSelector('[data-session-id="complete"]');
 assert.deepEqual(await page.locator('.session-button').evaluateAll(ns=>ns.map(n=>n.dataset.sessionId)),['metadata','child','complete','pending','failed','running']);
 await editFilter(page,'selectOption','#session-status','analyzed');
 await page.waitForFunction(()=>document.querySelectorAll('.session-button').length===2);
 assert.deepEqual(await page.locator('.session-button').evaluateAll(ns=>ns.map(n=>n.dataset.sessionId)),['child','complete']);
 assert.equal(await page.locator('[data-session-id="metadata"]').count(),0);
 for(const [query,expectedId] of [['native-cpm-7f12','complete'],['child','child'],['rollout-cpm-source-file.jsonl','complete'],['分析 CPM 优化','complete']]){const response=page.waitForResponse(r=>{const u=new URL(r.url());return u.pathname==='/trajectory/api/sessions'&&u.searchParams.get('q')===query});await page.fill('#session-search',query);await response;await page.waitForFunction(expected=>document.querySelectorAll('.session-button').length===1&&document.querySelector('.session-button')?.dataset.sessionId===expected,expectedId);}await page.fill('#session-search','');await page.waitForFunction(()=>document.querySelectorAll('.session-button').length===2);
 await page.locator('[data-session-id="child"]').click();
 await page.waitForFunction(()=>document.querySelector('#analysis-job-state')?.textContent==='旧快照，可查看');assert.equal(await page.locator('#analysis-view').count(),1);assert((await analysisText(page)).includes('当前展示历史版本的任务分段与开销，新增记录未计入当前任务开销'));assert(!(await analysisText(page)).includes('旧任务暂不展示'));assert.equal(await page.locator('#analyze-session').textContent(),'重新分析');await page.setViewportSize({width:390,height:844});assert((await analysisText(page)).includes('历史版本'));assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:process.argv[3]+'/workbench-historical-mobile.png',fullPage:true});await page.setViewportSize({width:1440,height:1000});await page.click('#analyze-session');await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('新版本的任务分析已排队或正在进行'));assert.equal(await page.locator('#analysis-view').count(),1);assert.equal(await page.locator('#analyze-session').count(),0);assert.equal(analysisPosts.length,1);assert(analysisPosts[0].mutation_id);childReanalysisStatus='failed';childHistorical=true;childQueued=true;await page.locator('[data-session-id="child"]').click();await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('新版本的任务分析失败'));assert.equal(await page.locator('#analysis-view').count(),1);assert.equal(await page.locator('#analyze-session').count(),0);assert.equal(await page.locator('[data-resume-job]').count(),1);childReanalysisStatus='queued';childHistorical=false;childQueued=false;await page.locator('[data-session-id="child"]').click();await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('上一版任务分段没有保留'));assert.equal(await page.locator('#analysis-view').count(),0);assert.equal(await page.locator('[data-session-id="child"]').count(),1);await page.waitForFunction(()=>document.querySelector('#analyze-session')?.textContent==='重新分析');await page.click('#analyze-session');await page.waitForFunction(()=>document.querySelector('#analysis-job-state')?.textContent==='等待分析');assert.equal(analysisPosts.length,2);assert(analysisPosts[1].mutation_id);
 await analysisText(page);await page.getByRole('button',{name:'查看父会话',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.analysis-title')?.textContent==='分析 CPM 优化');
 assert((await analysisText(page)).includes('已有摘要，不新增模型请求'));await page.getByText('本次分析调用与开销',{exact:true}).click();assert((await analysisText(page)).includes('推理强度 high'));assert((await analysisText(page)).includes('0.123 USD，已知小计，有计价缺口'));assert((await analysisText(page)).includes('实际扣费未知'));assert.equal(await page.getByRole('link',{name:'参考价格来源',exact:true}).getAttribute('href'),'https://docs.z.ai/guides/overview/pricing');
 await page.reload();await page.waitForSelector('[data-session-id="complete"]');
 assert.equal(await page.inputValue('#session-status'),'analyzed');assert.equal(await page.locator('.session-button').count(),2);
 await editFilter(page,'selectOption','#session-status','busy');await page.waitForSelector('[data-session-id="running"]');assert.equal(await page.locator('.session-button').count(),1);
 await editFilter(page,'selectOption','#session-status','failed');await page.waitForSelector('[data-session-id="failed"]');assert.equal(await page.locator('.session-button').count(),1);
 await editFilter(page,'selectOption','#session-status','not_started');await page.waitForSelector('[data-session-id="metadata"]');assert.equal(await page.locator('.session-button').count(),2);
 await page.click('#select-visible');assert((await page.locator('#selection-count').innerText()).includes('2'));
 await page.click('#submit-batch');await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('503'));
 failSubmit=false;await page.click('#submit-batch');await page.waitForSelector('.batch-panel');
 assert.equal(posts.length,2);assert.equal(posts[0].mutation_id,posts[1].mutation_id);assert.deepEqual(posts[1].session_ids,['metadata','pending']);assert.equal(posts[1].concurrency,4);
 assert((await page.locator('#batch-activity > summary').innerText()).includes('后台分析 0 / 2'));if(!await page.locator('#batch-activity').evaluate(n=>n.open))await page.locator('#batch-activity > summary').click();assert((await page.locator('.batch-panel').innerText()).includes('已完成 0 / 2'));assert((await page.locator('.batch-panel').innerText()).includes('3 / 12 批'));assert((await page.locator('.batch-panel').innerText()).includes('验证 CPM 编译器融合策略'));assert((await page.locator('.batch-panel').innerText()).includes('/research/embodied/ai-cpm'));assert(!(await page.locator('.batch-panel').innerText()).includes('outside-list'));await editFilter(page,'selectOption','#session-status','analyzed');await page.waitForFunction(()=>document.querySelectorAll('.session-button').length===2);assert((await page.locator('.batch-panel').textContent()).includes('验证 CPM 编译器融合策略'));assert.equal(await page.locator('[data-session-id="outside-list"]').count(),0);
 await page.reload();await page.waitForSelector('.batch-panel');assert(batchReads>=2);
 await editFilter(page,'selectOption','#session-status','all');await editFilter(page,'selectOption','#session-directory','/work/BatCave');await page.waitForSelector('[data-session-id="failed"]');assert.equal(await page.locator('.session-button').count(),2);
 await page.fill('#session-search','不存在的会话');await page.waitForFunction(()=>document.querySelector('#session-list').textContent.includes('当前筛选没有匹配会话'));
 await page.fill('#session-search','');await editFilter(page,'selectOption','#session-directory','');await editFilter(page,'selectOption','#session-sort','started_desc');await page.waitForSelector('[data-session-id="complete"]');
 assert.equal(await page.locator('.session-button').first().getAttribute('data-session-id'),'pending');
 assert(queries.some(q=>q.analysis_status==='analyzed'));assert(queries.some(q=>q.cwd==='/work/BatCave'));
 failList=true;await page.click('#sessions-refresh');await page.waitForFunction(()=>document.querySelector('#sessions-state').textContent.includes('保留上次'));
 await page.locator('[data-session-id="complete"]').click();await page.waitForSelector('#analysis-view');
 pendingSnapshot=true;await page.locator('[data-session-id="complete"]').click();await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('等待重新解析'));assert.equal(await page.locator('#analyze-session').count(),0);assert.equal(await page.locator('#analysis-view').count(),1);assert((await analysisText(page)).includes('优化 CPM'));assert.equal(analysisPosts.length,2);
 await page.locator('#analysis-content').evaluate(n=>{const spacer=document.createElement('div');spacer.style.height='1600px';n.append(spacer);n.scrollTop=600});
 const paneBox=await page.locator('#analysis-content').boundingBox(),tabsBox=await page.locator('.analysis-context').boundingBox();assert(tabsBox.y>=paneBox.y-2&&tabsBox.y<paneBox.y+20);
 await page.getByRole('button',{name:'分段时间线',exact:true}).click();
 const navPosition=await page.locator('#site-shell').evaluate(n=>getComputedStyle(n).position);assert.equal(navPosition,'sticky');assert(await page.locator('.section-nav').evaluate(n=>Boolean(n.closest('#site-shell'))));
 assert.equal(await page.locator('.analysis-context').evaluate(n=>getComputedStyle(n).position),'sticky');
 await page.screenshot({path:process.argv[3]+'/workbench-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:process.argv[3]+'/workbench-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',checks:['server-authoritative native/opaque/title search','status filter persistence','metadata-only excluded','source and time sorting','existing summary','parent navigation','stable batch retry','batch progress recovery','empty and stale list','mobile layout','historical snapshot stays visible','explicit reanalysis without hiding the saved tree','stale without retained snapshot','persistent navigation'],api_queries:queries.length}));
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});

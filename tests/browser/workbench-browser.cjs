const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),http=require('http'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
assert(!html.includes('\u00b7'));
const sessions=[
 {id:'complete',display_title:'分析 CPM 优化',cwd:'/research/embodied',started_at:'2026-10-01T06:00:00Z',last_activity_at:'2026-10-18T07:00:00Z',has_analysis:true,analysis_status:'complete',agent:'Codex',summary:'已有摘要，不新增模型请求'},
 {id:'metadata',display_title:'仅元信息部分上传',cwd:'/research/embodied',started_at:'2026-10-10T06:00:00Z',last_activity_at:'2026-10-19T06:00:00Z',has_analysis:false,analysis_status:'partial'},
 {id:'child',display_title:'子 Agent 验证稀疏矩阵',cwd:'/research/embodied',started_at:'2026-10-12T06:00:00Z',last_activity_at:'2026-10-18T08:00:00Z',has_analysis:true,analysis_status:'stale',parent_session_id:'complete'},
 {id:'pending',display_title:'新的 CPM 对照实验',cwd:'/research/embodied',started_at:'2026-10-17T06:00:00Z',last_activity_at:'2026-10-17T06:00:00Z',has_analysis:false,analysis_status:'not_started'},
 {id:'failed',display_title:'失败的工作流',cwd:'/work/BatCave',last_activity_at:'2026-10-16T06:00:00Z',has_analysis:false,analysis_status:'failed'},
 {id:'running',display_title:'正在分类',cwd:'/work/BatCave',last_activity_at:'2026-10-15T06:00:00Z',has_analysis:false,analysis_status:'running'}
];
let posts=[],batchReads=0,failSubmit=true,failList=false,childQueued=false;const analysisPosts=[];
const queries=[];
const batch={batch_id:'batch-test',status:'running',total:2,concurrency:4,counts:{running:1,queued:1},items:[{session_id:'metadata',status:'running',progress:{completed_chunks:3,total_chunks:12,model:'glm-test'},elapsed_seconds:22},{session_id:'pending',status:'queued'}]};
const server=http.createServer(async(req,res)=>{
 let body='';for await(const chunk of req)body+=chunk;
 res.setHeader('content-type','application/json');
 const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/trajectory/api/overview')return res.end(JSON.stringify({generated_at:'2026-10-19T06:00:00Z',projects:[],daily:[],anomalies:[],coverage:{},pricing:{prices:[]}}));
 if(url.pathname==='/api/services.json')return res.end(JSON.stringify({services:[]}));
 if(url.pathname==='/trajectory/api/sessions'){
  queries.push(Object.fromEntries(url.searchParams));
  if(failList){res.writeHead(503);return res.end('{}')}
  return res.end(JSON.stringify({sessions,directories:['/research/embodied','/work/BatCave']}));
 }
 if(url.pathname==='/trajectory/api/analysis-batches'&&req.method==='POST'){
  posts.push(JSON.parse(body));
  if(failSubmit){res.writeHead(503);return res.end('{}')}
  return res.end(JSON.stringify(batch));
 }
 if(url.pathname==='/trajectory/api/analysis-batches')return res.end(JSON.stringify({batches:[]}));
 if(url.pathname==='/trajectory/api/analysis-batches/batch-test'){batchReads++;return res.end(JSON.stringify(batch))}
 const match=url.pathname.match(/\/sessions\/([^/]+)\/analysis$/);
 if(match){if(match[1]==='child'&&req.method==='POST'){analysisPosts.push(JSON.parse(body));childQueued=true;return res.end(JSON.stringify({status:'queued'}))}const session=sessions.find(s=>s.id===match[1]);return res.end(JSON.stringify({session,has_analysis:session.has_analysis,status:session.id==='child'&&childQueued?'queued':session.analysis_status,coverage:{content_available:true,warnings:session.analysis_status==='stale'?['源记录已更新，旧分析未绑定当前证据']:[]},analysis_current:session.analysis_status!=='stale',analysis_cost:session.id==='complete'?{cost_status:'partial',known_subtotal_usd:0.123,calls:[{price:{source_url:'https://docs.z.ai/guides/overview/pricing',verified_at:'2026-10-19T04:00:00Z'}}]}:null,provenance:{model:'glm-test',reasoning_effort:'high',backend:'jindu',cost:null,chunks:2,analysis_usage:[{chunk:1,attempt:1,elapsed_seconds:1.2,valid:true,usage:{prompt_tokens:100,completion_tokens:20}}]},tasks:session.has_analysis&&session.analysis_status!=='stale'?[{id:'root',title:'优化 CPM',metrics:{input:100,known_subtotal_usd:0.1,cost_status:'complete'},segments:[]}]:[],operations:[]}))}
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
 await page.selectOption('#session-status','analyzed');
 await page.waitForFunction(()=>document.querySelectorAll('.session-button').length===2);
 assert.deepEqual(await page.locator('.session-button').evaluateAll(ns=>ns.map(n=>n.dataset.sessionId)),['child','complete']);
 assert.equal(await page.locator('[data-session-id="metadata"]').count(),0);
 await page.locator('[data-session-id="child"]').click();
 await page.waitForFunction(()=>document.querySelector('#analysis-job-state')?.textContent==='记录已更新，待重新分析');assert.equal(await page.locator('#analysis-view').count(),0);assert((await page.locator('#analysis-content').innerText()).includes('旧任务暂不展示'));assert.equal(await page.locator('[data-session-id="child"]').count(),1);assert.equal(await page.locator('#analyze-session').textContent(),'重新分析');await page.click('#analyze-session');await page.waitForFunction(()=>document.querySelector('#analysis-job-state')?.textContent==='等待分析');assert.equal(analysisPosts.length,1);assert(analysisPosts[0].mutation_id);
 await page.getByRole('button',{name:'查看父会话',exact:true}).click();
 await page.waitForFunction(()=>document.querySelector('.analysis-title')?.textContent==='分析 CPM 优化');
 assert((await page.locator('#analysis-content').innerText()).includes('已有摘要，不新增模型请求'));await page.getByText('本次分析调用与开销',{exact:true}).click();assert((await page.locator('#analysis-content').innerText()).includes('推理强度 high'));assert((await page.locator('#analysis-content').innerText()).includes('0.123 USD，已知小计，有计价缺口'));assert((await page.locator('#analysis-content').innerText()).includes('实际扣费未知'));assert.equal(await page.getByRole('link',{name:'参考价格来源',exact:true}).getAttribute('href'),'https://docs.z.ai/guides/overview/pricing');
 await page.reload();await page.waitForSelector('[data-session-id="complete"]');
 assert.equal(await page.inputValue('#session-status'),'analyzed');assert.equal(await page.locator('.session-button').count(),2);
 await page.selectOption('#session-status','busy');await page.waitForSelector('[data-session-id="running"]');assert.equal(await page.locator('.session-button').count(),1);
 await page.selectOption('#session-status','failed');await page.waitForSelector('[data-session-id="failed"]');assert.equal(await page.locator('.session-button').count(),1);
 await page.selectOption('#session-status','not_started');await page.waitForSelector('[data-session-id="metadata"]');assert.equal(await page.locator('.session-button').count(),2);
 await page.click('#select-visible');assert((await page.locator('#selection-count').innerText()).includes('2'));
 await page.click('#submit-batch');await page.waitForFunction(()=>document.querySelector('#batch-feedback').textContent.includes('503'));
 failSubmit=false;await page.click('#submit-batch');await page.waitForSelector('.batch-panel');
 assert.equal(posts.length,2);assert.equal(posts[0].mutation_id,posts[1].mutation_id);assert.deepEqual(posts[1].session_ids,['metadata','pending']);assert.equal(posts[1].concurrency,4);
 assert((await page.locator('.batch-panel').innerText()).includes('已完成 0 / 2'));await page.getByText('查看各会话进度',{exact:true}).click();assert((await page.locator('.batch-panel').innerText()).includes('3 / 12 批'));
 await page.reload();await page.waitForSelector('.batch-panel');assert(batchReads>=2);
 await page.selectOption('#session-status','all');await page.selectOption('#session-directory','/work/BatCave');await page.waitForSelector('[data-session-id="failed"]');assert.equal(await page.locator('.session-button').count(),2);
 await page.fill('#session-search','不存在的会话');await page.waitForFunction(()=>document.querySelector('#session-list').textContent.includes('当前筛选没有匹配会话'));
 await page.fill('#session-search','');await page.selectOption('#session-directory','');await page.selectOption('#session-sort','started_desc');await page.waitForSelector('[data-session-id="complete"]');
 assert.equal(await page.locator('.session-button').first().getAttribute('data-session-id'),'pending');
 assert(queries.some(q=>q.analysis_status==='analyzed'));assert(queries.some(q=>q.cwd==='/work/BatCave'));
 failList=true;await page.click('#sessions-refresh');await page.waitForFunction(()=>document.querySelector('#sessions-state').textContent.includes('保留上次'));
 await page.locator('[data-session-id="complete"]').click();await page.waitForSelector('#analysis-view');
 await page.locator('#analysis-content').evaluate(n=>{const spacer=document.createElement('div');spacer.style.height='1600px';n.append(spacer);n.scrollTop=600});
 const paneBox=await page.locator('#analysis-content').boundingBox(),tabsBox=await page.locator('.analysis-tabs').boundingBox();assert(tabsBox.y>=paneBox.y-2&&tabsBox.y<paneBox.y+20);
 await page.getByRole('button',{name:'分段时间线',exact:true}).click();
 const navPosition=await page.locator('.section-nav').evaluate(n=>getComputedStyle(n).position);assert.equal(navPosition,'sticky');
 assert.equal(await page.locator('.analysis-tabs').evaluate(n=>getComputedStyle(n).position),'sticky');
 await page.screenshot({path:process.argv[3]+'/workbench-desktop.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:process.argv[3]+'/workbench-mobile.png',fullPage:true});
 assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));assert.deepEqual(errors,[]);
 console.log(JSON.stringify({status:'passed',checks:['status filter persistence','metadata-only excluded','source and time sorting','existing summary','parent navigation','stable batch retry','batch progress recovery','empty and stale list','mobile layout','persistent navigation'],api_queries:queries.length}));
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1;server.close()});

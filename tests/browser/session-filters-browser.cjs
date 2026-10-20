// Filter inputs live in one native disclosure; reopen it before each scoped edit.
const openFilters = page => page.locator('#workspace-filters').evaluate(n => {n.open = true;});
const editFilter = async (page, method, ...args) => {await openFilters(page);await page[method](...args);await page.locator('#workspace-filters').evaluate(n=>{n.open=false;});};
// Real controls and delayed HTTP responses exercise coalescing and stale-scope races.
const fs=require('fs'),http=require('http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE),html=fs.readFileSync(process.argv[2],'utf8');
const rows=[
 {id:'alpha',display_title:'Alpha analysis',native_session_id:'native-alpha',cwd:'/workspace/a',project:'project-a',started_at:'2026-10-14T00:00:00Z',last_activity_at:'2026-10-18T00:00:00Z',has_analysis:true,analysis_status:'complete'},
 {id:'beta',display_title:'Beta analysis',native_session_id:'native-beta',cwd:'/workspace/b',project:'project-b',started_at:'2026-10-11T00:00:00Z',last_activity_at:'2026-10-17T00:00:00Z',has_analysis:true,analysis_status:'complete'},
 {id:'gamma',display_title:'Gamma analysis',native_session_id:'native-gamma',cwd:'/workspace/a',project:'project-a',started_at:'2026-10-12T00:00:00Z',last_activity_at:'2026-10-16T00:00:00Z',has_analysis:true,analysis_status:'complete'},
 {id:'pending',display_title:'Pending source',native_session_id:'native-pending',cwd:'/workspace/b',project:'project-b',started_at:'2026-10-13T00:00:00Z',last_activity_at:'2026-10-15T00:00:00Z',has_analysis:false,analysis_status:'not_started'}
];
const requests=[],held=[],holdQueue=[],pageErrors=[];let overviewReads=0,active=0,maxActive=0,failNext=false,holdOverview=false,overviewHeld=null,holdBatch=false,batchHeld=null,batchStatus='running';
const poison={sessions:[],directories:['/stale-response-only'],next_cursor:'stale-cursor'};
const responseFor=q=>{
 const matches=rows.filter(s=>(!q.project||s.project===q.project)&&(!q.cwd||s.cwd===q.cwd)&&(!q.since||s.last_activity_at.slice(0,10)>=q.since)&&(!q.until||s.last_activity_at.slice(0,10)<=q.until)&&(!q.q||[s.id,s.native_session_id,s.display_title].some(v=>v.toLowerCase().includes(q.q.toLowerCase())))&&(q.analysis_status!=='analyzed'||s.has_analysis)&&(q.analysis_status!=='failed'||s.analysis_status==='failed'));
 matches.sort((a,b)=>q.sort==='started_desc'?b.started_at.localeCompare(a.started_at):q.sort==='directory'?a.cwd.localeCompare(b.cwd)||b.last_activity_at.localeCompare(a.last_activity_at):b.last_activity_at.localeCompare(a.last_activity_at));
 const offset=q.cursor==='page-2'?2:0;return {sessions:matches.slice(offset,offset+2),directories:['/workspace/a','/workspace/b'],projects:[{id:'project-a',name:'Project A'},{id:'project-b',name:'Project B'}],next_cursor:offset+2<matches.length?'page-2':null};
};
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');res.setHeader('content-type','application/json');
 if(url.pathname==='/trajectory/api/overview'){overviewReads++;const reply=()=>res.end(JSON.stringify({generated_at:'2026-10-19T00:00:00Z',projects:[{id:'project-a',name:'Project A'},{id:'project-b',name:'Project B'}],daily:[],anomalies:[],coverage:{},pricing:{prices:[]}}));if(holdOverview){overviewHeld=reply;return}return reply()}
 if(url.pathname==='/trajectory/api/sessions'){
  const q=Object.fromEntries(url.searchParams),entry={q};requests.push(entry);maxActive=Math.max(maxActive,++active);res.once('finish',()=>active--);
  const control=holdQueue.shift(),fail=failNext;failNext=false;
  const release=()=>{if(control?.error||fail){res.statusCode=503;res.end('{}')}else res.end(JSON.stringify(control?.poison?poison:responseFor(q)))};
  if(control){held.push({name:control.name,q,release});return}return release();
 }
 const batch=()=>({batch_id:'fixture-batch',status:batchStatus,concurrency:1,total:1,counts:{[batchStatus]:1},items:[{session_id:'alpha',status:batchStatus,session:rows[0]}]});
 if(url.pathname==='/trajectory/api/analysis-batches')return res.end(JSON.stringify({batches:[batch()]}));
 if(url.pathname==='/trajectory/api/analysis-batches/fixture-batch'){const reply=()=>res.end(JSON.stringify(batch()));if(holdBatch){batchHeld=reply;return}return reply()}
 const analysis=url.pathname.match(/\/sessions\/([^/]+)\/analysis$/);
 if(analysis){assert.equal(req.method,'GET');const session=rows.find(s=>s.id===analysis[1]);return res.end(JSON.stringify({session,status:'complete',has_analysis:true,analysis_current:true,tasks:[],operations:[],coverage:{content_available:true,warnings:[]}}))}
 if(url.pathname==='/api/services.json')return res.end('{"services":[]}');
 if(url.pathname.endsWith('.svg')){res.setHeader('content-type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg"/>')}
 res.setHeader('content-type','text/html');res.end(html);
});
const until=async(check,message,timeout=5000)=>{const deadline=Date.now()+timeout;while(!check()){if(Date.now()>deadline)throw Error(message);await new Promise(r=>setTimeout(r,10))}};
(async()=>{await new Promise(r=>server.listen(0,'127.0.0.1',r));const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>pageErrors.push(e.message));
 const idle=()=>page.waitForFunction(()=>!document.querySelector('#sessions-refresh').disabled);
 const ids=()=>page.locator('.session-button').evaluateAll(ns=>ns.map(n=>n.dataset.sessionId));
 const requested=async n=>{await until(()=>requests.length>=n,'Expected listing request');await idle()};
 const reset=async()=>{const n=requests.length;await page.fill('#session-search','');await editFilter(page,'selectOption','#session-status','all');await editFilter(page,'selectOption','#session-directory','');await editFilter(page,'selectOption','#session-sort','last_activity_desc');await editFilter(page,'selectOption','#project','');await editFilter(page,'fill','#since','');await editFilter(page,'fill','#until','');await requested(n+1);assert.deepEqual(await ids(),['alpha','beta'])};
 const chooseAlpha=async()=>{await page.locator('[data-session-id="alpha"]').click();await page.waitForFunction(()=>document.querySelector('.analysis-title')?.textContent==='Alpha analysis')};
 await page.goto('http://127.0.0.1:'+server.address().port+'/trajectory/');await page.waitForSelector('[data-session-id="alpha"]');await idle();
 let n=requests.length;await editFilter(page,'selectOption','#session-status','analyzed');await page.fill('#session-search','native-alpha');await requested(n+1);assert.equal(requests.length,n+1);assert.equal(requests.at(-1).q.analysis_status,'analyzed');assert.equal(requests.at(-1).q.q,'native-alpha');assert.deepEqual(await ids(),['alpha']);await page.waitForTimeout(350);assert.equal(requests.length,n+1);
 // An actual batch poll cannot bypass a pending filter debounce with an older query.
 holdBatch=true;await until(()=>batchHeld,'Expected background batch poll',10000);n=requests.length;await editFilter(page,'selectOption','#session-status','all');batchStatus='complete';holdBatch=false;batchHeld();await page.waitForFunction(()=>document.querySelector('.batch-panel')?.textContent.includes('已完成 1 / 1'));assert.equal(requests.length,n);await page.fill('#session-search','native-beta');await requested(n+1);assert.equal(requests.length,n+1);assert.equal(requests.at(-1).q.analysis_status,'all');assert.equal(requests.at(-1).q.q,'native-beta');
 n=requests.length;await editFilter(page,'selectOption','#session-status','analyzed');await page.fill('#session-search','native-alpha');await requested(n+1);
 // All controls participate in the same timer, and every scope field survives reload.
 n=requests.length;await editFilter(page,'selectOption','#session-directory','/workspace/a');await editFilter(page,'selectOption','#session-sort','directory');await editFilter(page,'selectOption','#project','project-a');await editFilter(page,'fill','#since','2026-10-01');await editFilter(page,'fill','#until','2026-10-31');await requested(n+1);assert.equal(requests.length,n+1);
 const scope={analysis_status:'analyzed',cwd:'/workspace/a',sort:'directory',project:'project-a',since:'2026-10-01',until:'2026-10-31',q:'native-alpha'};for(const [k,v]of Object.entries(scope))assert.equal(requests.at(-1).q[k],v);
 n=requests.length;await page.reload();await requested(n+1);assert.equal(overviewReads,0,'Task view must populate projects without loading overview');assert.equal(await page.inputValue('#project'),'project-a');assert.equal(requests.length,n+1);await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);assert.equal(requests.length,n+1);assert.deepEqual(await ids(),['alpha']);for(const [k,v]of Object.entries(scope))assert.equal(requests.at(-1).q[k],v);assert.equal(await page.inputValue('#project'),'project-a');assert.equal(await page.inputValue('#since'),'2026-10-01');assert.equal(await page.inputValue('#until'),'2026-10-31');
 await reset();await chooseAlpha();await page.locator('[data-select-session="alpha"]').check();
 const cases=[['status','#session-status','analyzed'],['directory','#session-directory','/workspace/a'],['sort','#session-sort','started_desc'],['project','#project','project-a'],['since','#since','2026-10-02'],['until','#until','2026-10-30']];
 for(const [name,selector,value]of cases){
  await reset();await chooseAlpha();n=requests.length;holdQueue.push({name:'old-'+name,poison:true},{name:'latest-'+name});await page.click('#sessions-refresh');await until(()=>held.some(h=>h.name==='old-'+name),'Old request missing');
  if(selector==='#since'||selector==='#until')await editFilter(page,'fill',selector,value);else await editFilter(page,'selectOption',selector,value);
  held.find(h=>h.name==='old-'+name).release();await until(()=>held.some(h=>h.name==='latest-'+name),'Latest scope request missing');
  assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');assert.deepEqual(await ids(),['alpha','beta']);assert.equal(await page.locator('#session-directory option[value="/stale-response-only"]').count(),0);assert.equal(await page.locator('#selection-count').textContent(),'已选择 1 个会话');
  held.find(h=>h.name==='latest-'+name).release();await idle();assert.equal(requests.length,n+2);assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');
 }
 // Several edits during one in-flight request produce one latest-scope successor.
 await reset();await chooseAlpha();n=requests.length;holdQueue.push({name:'old-many',poison:true},{name:'latest-many'});await page.click('#sessions-refresh');await until(()=>held.some(h=>h.name==='old-many'),'Old request missing');await editFilter(page,'selectOption','#session-status','analyzed');await editFilter(page,'selectOption','#session-directory','/workspace/a');await editFilter(page,'fill','#since','2026-10-01');await editFilter(page,'selectOption','#session-sort','directory');held.find(h=>h.name==='old-many').release();await until(()=>held.some(h=>h.name==='latest-many'),'Merged latest request missing');assert.equal(requests.length,n+2);held.find(h=>h.name==='latest-many').release();await idle();await page.waitForTimeout(350);assert.equal(requests.length,n+2);
 // An old-scope HTTP failure cannot overwrite the current scope's feedback or detail.
 await reset();await chooseAlpha();holdQueue.push({name:'old-error',error:true},{name:'latest-after-error'});await page.click('#sessions-refresh');await until(()=>held.some(h=>h.name==='old-error'),'Old error request missing');await editFilter(page,'selectOption','#session-status','analyzed');held.find(h=>h.name==='old-error').release();await until(()=>held.some(h=>h.name==='latest-after-error'),'Recovery request missing');assert(!(await page.locator('#sessions-state').textContent()).includes('503'));assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');held.find(h=>h.name==='latest-after-error').release();await idle();
 // A current-scope failure retains the last good page and can recover by manual refresh.
 failNext=true;await page.click('#sessions-refresh');await page.waitForFunction(()=>document.querySelector('#sessions-state').textContent.includes('保留上次'));assert((await page.locator('#sessions-state').textContent()).includes('503'));assert.deepEqual(await ids(),['alpha','beta']);assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');n=requests.length;await page.click('#sessions-refresh');await requested(n+1);assert(!(await page.locator('#sessions-state').textContent()).includes('503'));
 // Valid pagination appends without duplicates or clearing the selected analysis.
 await reset();await chooseAlpha();n=requests.length;await page.click('#sessions-more');await requested(n+1);assert.equal(requests.at(-1).q.cursor,'page-2');assert.deepEqual(await ids(),['alpha','beta','gamma','pending']);assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');
 // A page response from an older scope cannot replace its successor's cursor or selection.
 await reset();await chooseAlpha();holdQueue.push({name:'old-page',poison:true},{name:'new-first-page'});await page.click('#sessions-more');await until(()=>held.some(h=>h.name==='old-page'),'Old append missing');await editFilter(page,'selectOption','#session-directory','/workspace/a');held.find(h=>h.name==='old-page').release();await until(()=>held.some(h=>h.name==='new-first-page'),'New first page missing');assert.equal(await page.locator('.analysis-title').textContent(),'Alpha analysis');assert.equal(held.find(h=>h.name==='new-first-page').q.cursor,undefined);held.find(h=>h.name==='new-first-page').release();await idle();assert.deepEqual(await ids(),['alpha','gamma']);assert.equal(await page.locator('#sessions-more').isHidden(),true);
 // Pagination clicked during debounce flushes the new scope as a first page.
 await reset();n=requests.length;await editFilter(page,'selectOption','#session-directory','/workspace/a');await page.locator('#sessions-more').focus();await page.keyboard.press('Enter');await requested(n+1);assert.equal(requests.at(-1).q.cursor,undefined);assert.deepEqual(await ids(),['alpha','gamma']);
 assert.equal(maxActive,1);assert.deepEqual(pageErrors,[]);await page.setViewportSize({width:390,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:process.argv[3]+'/session-filters-mobile.png',fullPage:true});
 const result={result:'passed',checks:['one final request for rapid status and native search','all filter controls coalesce','background batch poll respects pending debounce','cold reload preserves full scope before delayed overview','full-scope reload persistence','six non-search stale-scope races preserve detail directories cursor and selection','multiple in-flight edits queue once','stale-scope errors ignored','current failure retains last good results and recovers','same-scope pagination appends','stale append restarts latest first page','pagination flush respects scope','one listing request in flight','mobile overflow'],listing_requests:requests.length,max_concurrent_listing_requests:maxActive,page_errors:pageErrors};fs.writeFileSync(process.argv[3]+'/session-filters-result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();server.close()}})().catch(e=>{console.error(e);process.exitCode=1;server.close()});

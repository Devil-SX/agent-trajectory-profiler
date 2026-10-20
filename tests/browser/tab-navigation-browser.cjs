// Filter inputs live in one native disclosure; reopen it before each scoped edit.
const openFilters = page => page.locator('#workspace-filters').evaluate(n => {n.open = true;});
const editStatisticFilter=async(page,method,...args)=>{await page.locator('#statistics-filters').evaluate(n=>{n.open=true});await page[method](...args);await page.locator('#statistics-filters').evaluate(n=>{n.open=false})};
const editFilter = async (page, method, ...args) => {await openFilters(page);await page[method](...args);await page.locator('#workspace-filters').evaluate(n=>{n.open=false;});};
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),http=require('http'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8'),output=process.argv[3];
let delay=0,fail=false,requests=[],overviewRequests=0,sessionRequests=0;
const payload=since=>({generated_at:'2026-10-20T06:00:00Z',projects:[{id:'embodied',name:since||'具身智能',input:100,output:20,calls:1,human_interactions:1,human_input_chars:12,missing_human_input_chars:0,unknown_origin_interactions:0},...Array.from({length:31},(_,i)=>({id:'project-'+i,name:'项目'+i,input:100,output:20,calls:1}))],daily:[],anomalies:[],coverage:{sources:2},pricing:{prices:[]}});
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');res.setHeader('content-type','application/json');requests.push({path:url.pathname,search:url.search,method:req.method});
 if(url.pathname==='/trajectory/research.js'){res.setHeader('content-type','text/javascript');return res.end("window.TrajectoryResearch={mount:async function(target,api){await api.request('/api/stage-studies');target.textContent='研究结果 fixture';}};")}
 if(url.pathname==='/trajectory/research.css'){res.setHeader('content-type','text/css');return res.end('')}
 if(url.pathname==='/trajectory/api/stage-studies')return res.end('{\"studies\":[]}');
 if(url.pathname==='/trajectory/api/overview'){overviewRequests++;const since=url.searchParams.get('since'),wait=delay,failed=fail;await new Promise(r=>setTimeout(r,wait));if(failed){res.writeHead(503);return res.end('{}')}return res.end(JSON.stringify(payload(since)))}
 if(url.pathname==='/trajectory/api/sessions'){sessionRequests++;await new Promise(r=>setTimeout(r,delay));return res.end(JSON.stringify({sessions:[{id:'one',display_title:'验证 CPM 性能',cwd:'/research/embodied',analysis_status:'complete',has_analysis:true,started_at:'2026-10-01T06:00:00Z'}],directories:['/research/embodied']}))}
 if(url.pathname==='/trajectory/api/analysis-batches')return res.end('{"batches":[]}');
 if(url.pathname==='/trajectory/api/sessions/one/analysis'){await new Promise(r=>setTimeout(r,delay));return res.end(JSON.stringify({status:'complete',session:{id:'one',display_title:'验证 CPM 性能'},tasks:[{id:'task',title:'测试分段',segments:[],metrics:{input:100}}],operations:[],coverage:{content_available:true}}))}
 if(url.pathname==='/api/services.json')return res.end('{"services":[{"id":"trajectory","name":"踪流"}]}');
 if(url.pathname.endsWith('.svg')){res.setHeader('content-type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="42" height="42"><rect width="42" height="42" rx="10" fill="#75bbf7"/></svg>')}
 res.setHeader('content-type','text/html');res.end(html);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
 try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));
 delay=600;await page.goto(origin+'/trajectory/');await page.waitForSelector('#session-list .loading-orbit');assert.equal(await page.locator('#session-list').getAttribute('aria-busy'),'true');await page.screenshot({path:output+'/sessions-loading.png',fullPage:true});
 await page.waitForSelector('[data-session-id="one"]');assert.equal(overviewRequests,0);assert.equal(sessionRequests,1);assert.equal(await page.locator('[role=tabpanel]:visible').count(),1);
 await page.locator('[data-session-id="one"]').click();await page.waitForSelector('#analysis-content .loading-state');await page.waitForSelector('.task-select');assert.equal(await page.locator('#analysis-content').getAttribute('aria-busy'),'false');
 await page.click('#tab-overview');await page.waitForSelector('#feedback-overview .loading-orbit');assert.equal(await page.locator('#view-overview').getAttribute('aria-busy'),'true');await page.screenshot({path:output+'/overview-loading-desktop.png',fullPage:true});
 // Another summary view joins the same pending read, not another HTTP request.
 await page.click('#tab-human-trends');await page.waitForFunction(()=>document.querySelector('#view-human-trends').getAttribute('aria-busy')==='false');assert.equal(overviewRequests,1);
 for(const id of ['trends','coverage','details','overview']){await page.click('#tab-'+id);assert.equal(await page.locator('[role=tabpanel]:visible').count(),1);assert.equal(await page.locator('#tab-'+id).getAttribute('aria-selected'),'true')}
 assert.equal(overviewRequests,1);assert.equal(sessionRequests,1);
 await page.click('#tab-task-analysis');assert.equal(await page.locator('.task-select').count(),1);assert.equal(sessionRequests,1);
 // Hidden views stay idle even as the shared date scope changes.
 await editFilter(page,'fill','#since','2026-10-02');await page.locator('#since').dispatchEvent('change');await page.waitForTimeout(350);assert.equal(overviewRequests,1);await page.waitForFunction(()=>document.querySelector('#session-list').getAttribute('aria-busy')==='false');assert.equal(sessionRequests,2);
 await page.click('#tab-trends');await page.waitForFunction(()=>document.querySelector('#view-trends').getAttribute('aria-busy')==='false');assert.equal(overviewRequests,1);
 // Returning to cached data and repeated tab selection never starts a new request.
 await page.click('#tab-overview');await page.click('#tab-overview');assert.equal(overviewRequests,1);assert.equal(sessionRequests,2);
 // Replace a slow scope request with a newer scope; old payload must not win.
 delay=650;await editStatisticFilter(page,'fill','#overview-since','2026-10-03');await page.locator('#overview-since').dispatchEvent('change');await page.waitForTimeout(60);delay=20;await editStatisticFilter(page,'fill','#overview-since','2026-10-04');await page.locator('#overview-since').dispatchEvent('change');await page.waitForFunction(()=>document.querySelector('#overview-project option[value=embodied]')?.textContent==='2026-10-04');await page.waitForTimeout(750);assert.equal(await page.locator('#overview-project option[value=embodied]').textContent(),'2026-10-04');assert.equal(sessionRequests,2);
 // Reverting to a cached scope stops the obsolete spinner immediately.
 delay=650;await editStatisticFilter(page,'fill','#overview-since','2026-10-05');await page.locator('#overview-since').dispatchEvent('change');await page.waitForTimeout(50);await editStatisticFilter(page,'fill','#overview-since','2026-10-04');await page.locator('#overview-since').dispatchEvent('change');assert.equal(await page.locator('#view-overview').getAttribute('aria-busy'),'false');assert.equal(await page.locator('#overview-project option[value=embodied]').textContent(),'2026-10-04');delay=20;
 fail=true;await page.click('#refresh');await page.waitForSelector('#feedback-overview .retry-feedback');assert.equal(await page.locator('#overview .card').count(),6);fail=false;await page.getByRole('button',{name:'重新加载',exact:true}).click();await page.waitForFunction(()=>document.querySelector('#view-overview').getAttribute('aria-busy')==='false');assert.equal(await page.locator('#feedback-overview .retry-feedback').count(),0);
 // Automatic tab activation, roving tabindex, Home/End, persistence and mobile overflow.
 await page.focus('#tab-overview');await page.keyboard.press('ArrowRight');assert.equal(await page.locator('#tab-human-trends').getAttribute('aria-selected'),'true');assert.equal(await page.locator('[role=tab][tabindex="0"]').count(),1);await page.keyboard.press('End');assert.equal(await page.locator('#tab-research').getAttribute('aria-selected'),'true');await page.waitForFunction(()=>document.querySelector('#view-research')?.textContent.includes('研究结果 fixture'));const researchReads=requests.filter(r=>r.path==='/trajectory/api/stage-studies').length;assert.equal(researchReads,1);const researchOverviewReads=overviewRequests;await page.click('#tab-overview');await page.click('#tab-research');assert.equal(requests.filter(r=>r.path==='/trajectory/api/stage-studies').length,researchReads);assert.equal(overviewRequests,researchOverviewReads);await page.focus('#tab-research');await page.keyboard.press('Home');assert.equal(await page.locator('#tab-task-analysis').getAttribute('aria-selected'),'true');await page.waitForFunction(()=>document.querySelector('#session-list').getAttribute('aria-busy')==='false');
 await page.click('#tab-coverage');const beforeReload=sessionRequests;await page.reload();await page.waitForFunction(()=>document.querySelector('#view-coverage').getAttribute('aria-busy')==='false');assert.equal(sessionRequests,beforeReload);assert.equal(await page.locator('#tab-coverage').getAttribute('aria-selected'),'true');
 await page.setViewportSize({width:390,height:844});delay=650;await page.click('#coverage-refresh');await page.waitForSelector('#feedback-coverage .loading-state');await page.screenshot({path:output+'/coverage-loading-mobile.png',fullPage:true});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.emulateMedia({reducedMotion:'reduce'});assert.equal(await page.locator('#feedback-coverage .loading-orbit').evaluate(n=>getComputedStyle(n).animationName),'none');await page.waitForFunction(()=>document.querySelector('#view-coverage').getAttribute('aria-busy')==='false');await page.screenshot({path:output+'/coverage-mobile.png',fullPage:true});
 await page.click('#tab-task-analysis');await page.evaluate(()=>{document.querySelector('#analysis-content').style.minHeight='2600px';scrollTo(0,1800)});await page.click('#tab-details');const heading=await page.locator('#details h2').boundingBox();const nav=await page.locator('.section-nav').boundingBox();assert(heading.y>=nav.y+nav.height&&heading.y<844,'Switching a long view must reveal the selected view heading');

 assert.equal(await page.locator('#session-search').evaluate(n=>n.closest('[role=tabpanel]').id),'view-task-analysis');
 assert.equal(await page.locator('#workspace-filters').evaluate(n=>n.closest('[role=tabpanel]').id),'view-task-analysis');
 assert.equal(await page.locator('#site-shell input,#site-shell select,#site-shell details').count(),0);
 assert.equal(await page.locator('#view-coverage input,#view-coverage select').count(),0);
 await page.click('#tab-overview');assert.equal(await page.locator('#statistics-controls').evaluate(n=>n.closest('[role=tabpanel]').id),'view-overview');assert.equal(await page.inputValue('#overview-since'),'2026-10-04');assert.equal(await page.inputValue('#since'),'2026-10-02');
 await page.click('#tab-human-trends');assert.equal(await page.inputValue('#overview-since'),'');assert.equal(await page.locator('#statistics-controls').evaluate(n=>n.closest('[role=tabpanel]').id),'view-human-trends');
 await page.goBack();await page.waitForFunction(()=>document.querySelector('#tab-overview').getAttribute('aria-selected')==='true');assert.equal(await page.inputValue('#overview-since'),'2026-10-04');
 const stickyChecks=[];
 for(const width of [1440,390]){
  await page.setViewportSize({width,height:844});await page.click('#tab-details');await page.locator('#view-details .view-body').evaluate(n=>{n.style.minHeight='2600px'});await page.evaluate(()=>scrollTo(0,1400));
  const shell=await page.locator('#site-shell').boundingBox(),logo=await page.locator('.brand img').boundingBox(),navigation=await page.locator('.section-nav').boundingBox();
  assert(shell.y>=-1&&shell.y<2,'Shared site shell stays at viewport top');assert(logo.y>=0&&logo.y+logo.height<844);assert(navigation.y>=logo.y&&navigation.y+navigation.height<844);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:output+'/sticky-navigation-'+width+'.png',fullPage:false});await page.click('#tab-overview');const first=await page.locator('#statistics-controls').boundingBox(),nav=await page.locator('#site-shell').boundingBox();assert(first.y>=nav.y+nav.height-1,'Tab controls must start below the sticky header');stickyChecks.push({width,header_height:shell.height,logo_y:logo.y,nav_y:navigation.y});
 }
 assert.equal(requests.filter(r=>r.method!=='GET').length,0);assert.deepEqual(errors,[]);
 const result={result:'passed',cases:['seven exclusive tab panels including a lazy research module','task-first landing skips overview','summary-first reload skips sessions','shared overview in-flight coalescing','cached repeated visits','independent per-tab statistics scopes cannot change task filters','late response cannot replace new scope','retained analysis on tab return','visible animated skeletons','retry retains data','roving keyboard focus','persisted selected tab','mobile no horizontal overflow','long view switching reveals target heading','reduced motion','DOM-owned local controls','sticky logo and navigation on desktop and mobile','history restores tab-local filters','GET-only'],stickyChecks,overviewRequests,sessionRequests,pageErrors:errors};fs.writeFileSync(output+'/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();await new Promise(r=>server.close(r))}
})().catch(e=>{console.error(e);process.exit(1)});

/* Real host and component: the plan drawer stays lazy and belongs to the task tab. */
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const source=process.argv[2],output=process.argv[3];fs.mkdirSync(output,{recursive:true});
const html=fs.readFileSync(path.join(source,'dashboard.html'),'utf8').replaceAll('__TRAJECTORY_RESEARCH_REVISION__','fixture').replaceAll('__TRAJECTORY_SCHEDULE_REVISION__','fixture');
const requests=[];let assetFailure=false,denied=false,assetDelay=400;
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://fixture');requests.push({path:u.pathname,method:req.method});
 if(req.method!=='GET'){res.writeHead(405);return res.end();}
 if(u.pathname==='/trajectory/'){res.setHeader('content-type','text/html; charset=utf-8');return res.end(html);}
 if(['/trajectory/schedules.js','/trajectory/schedules.css'].includes(u.pathname)){
  await new Promise(resolve=>setTimeout(resolve,assetDelay));
  if(assetFailure){res.writeHead(503);return res.end('');}
  res.setHeader('content-type',u.pathname.endsWith('.js')?'text/javascript; charset=utf-8':'text/css; charset=utf-8');return res.end(fs.readFileSync(path.join(source,u.pathname.split('/').pop())));
 }
 res.setHeader('content-type','application/json; charset=utf-8');
 if(u.pathname==='/trajectory/api/analysis-schedules'){
  if(denied){res.writeHead(403);return res.end('{}');}
  return res.end(JSON.stringify({schedules:[],policy:{}}));
 }
 if(u.pathname==='/trajectory/api/sessions')return res.end(JSON.stringify({sessions:[],total:0,projects:[],directories:[],metrics_included:false,coverage:{}}));
 if(u.pathname==='/trajectory/api/analysis-batches')return res.end('{"batches":[]}');
 if(u.pathname==='/trajectory/api/coverage')return res.end('{"sources":0,"generated_at":"2026-10-21T00:00:00Z"}');
 if(u.pathname.includes('services.json'))return res.end('{"services":[]}');
 if(u.pathname.endsWith('.svg')){res.setHeader('content-type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg" width="42" height="42"/>');}
 res.writeHead(404);res.end('{}');
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const url='http://127.0.0.1:'+server.address().port+'/trajectory/';
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});const errors=[];
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(e.message));await page.goto(url);await page.waitForFunction(()=>document.querySelector('#session-list')?.getAttribute('aria-busy')==='false');
  assert(!requests.some(r=>r.path.includes('schedules')));assert.equal(await page.locator('#schedule-plans').evaluate(n=>n.closest('[role=tabpanel]').id),'view-task-analysis');
  await page.locator('#schedule-plans>summary').click();await page.locator('#schedule-plans-content .loading-orbit').waitFor();await page.getByLabel('计划名称').waitFor();assert.equal(await page.locator('#schedule-plans').getAttribute('aria-busy'),'false');
  const reads=()=>requests.filter(r=>r.path==='/trajectory/api/analysis-schedules').length;assert.equal(reads(),1);assert(!requests.some(r=>r.path.endsWith('/overview')));
  await page.getByLabel('计划名称').focus();await page.keyboard.press('Escape');assert.equal(await page.locator('#schedule-plans').evaluate(n=>n.open),false);assert.equal(await page.evaluate(()=>document.activeElement.parentElement.id),'schedule-plans');
  await page.keyboard.press('Enter');await page.getByLabel('计划名称').waitFor();assert.equal(reads(),1);await page.screenshot({path:path.join(output,'scheduling-workbench-desktop.png'),fullPage:true});
  await page.click('#tab-coverage');assert.equal(await page.locator('#schedule-plans').isVisible(),false);await page.waitForFunction(()=>document.querySelector('#view-coverage').getAttribute('aria-busy')==='false');assert.equal(reads(),1);
  await page.click('#tab-task-analysis');await page.setViewportSize({width:390,height:844});await page.locator('#schedule-plans>summary').click();await page.getByLabel('计划名称').waitFor();const bounds=await page.locator('#schedule-plans-content').boundingBox();assert(bounds.x>=0&&bounds.x+bounds.width<=390);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await page.screenshot({path:path.join(output,'scheduling-workbench-mobile.png'),fullPage:true});await page.getByRole('button',{name:'保存计划',exact:true}).scrollIntoViewIfNeeded();assert(await page.getByRole('button',{name:'保存计划',exact:true}).isVisible());assert(await page.locator('#schedule-plans-content').evaluate(n=>n.scrollTop>0));await page.screenshot({path:path.join(output,'scheduling-workbench-mobile-actions.png'),fullPage:true});
  assert.equal(await page.locator('#site-shell input,#site-shell select,#site-shell details').count(),0);
  // A fresh page has no global module cache. A failed asset must support retry.
  const retry=await browser.newPage({viewport:{width:1440,height:1000}});retry.on('pageerror',e=>errors.push(e.message));assetFailure=true;assetDelay=20;await retry.goto(url);await retry.locator('#schedule-plans>summary').click();await retry.getByRole('button',{name:'重新加载定时计划',exact:true}).waitFor();assetFailure=false;denied=true;await retry.getByRole('button',{name:'重新加载定时计划',exact:true}).click();await retry.getByRole('button',{name:'重新读取',exact:true}).waitFor();assert.match(await retry.locator('.schedule-status').innerText(),/403/);denied=false;await retry.getByRole('button',{name:'重新读取',exact:true}).click();await retry.getByLabel('计划名称').waitFor();assert.equal(await retry.locator('.schedule-error').count(),0);
  assert.equal(requests.filter(r=>r.method!=='GET').length,0);assert.deepEqual(errors,[]);assert(!await page.locator('#schedule-plans-content').textContent().then(t=>t.includes('\u00b7')));fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({status:'PASS',checks:13,requests,errors},null,2));console.log('PASS 13 real-host scheduling workbench checks');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);server.close();process.exit(1)});

const analysisText = async page => {await page.locator('.analysis-context-details').evaluateAll(ns=>ns.forEach(n=>{n.open=true;}));return page.locator('#analysis-content').innerText();};
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),http=require('http'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2],'utf8');
assert(!html.includes('\u00b7'));
const sessions=[
 {id:'recover',display_title:'验证 CPM 布局优化',cwd:'/research/embodied',analysis_status:'failed',has_analysis:false},
 {id:'uncertain',display_title:'核对关键路径结果',cwd:'/research/embodied',analysis_status:'failed',has_analysis:false},
];
const resume=(id)=>({eligible:id==='recover',reason:id==='recover'?'eligible':'prior_call_uncertain',job_id:'job-'+id,generation:0,completed_chunks:8,max_generations:3});
const posts=[];let failResume=true,queued=false;
const batch=()=>({batch_id:'recovery-batch',status:queued?'running':'failed',total:2,concurrency:4,counts:{failed:queued?1:2,queued:queued?1:0},items:sessions.map(s=>({session_id:s.id,session:s,job_id:'job-'+s.id,status:s.id==='recover'&&queued?'queued':'failed',progress:{completed_chunks:8,total_chunks:30},resume:resume(s.id)}))});
const server=http.createServer(async(req,res)=>{
 let body='';for await(const chunk of req)body+=chunk;
 res.setHeader('content-type','application/json');const url=new URL(req.url,'http://localhost');
 if(url.pathname==='/trajectory/api/overview')return res.end(JSON.stringify({projects:[],daily:[],anomalies:[],coverage:{},pricing:{prices:[]}}));
 if(url.pathname==='/api/services.json')return res.end(JSON.stringify({services:[]}));
 if(url.pathname==='/trajectory/api/sessions')return res.end(JSON.stringify({sessions,directories:['/research/embodied']}));
 if(url.pathname==='/trajectory/api/analysis-batches')return res.end(JSON.stringify({batches:[batch()]}));
 if(url.pathname==='/trajectory/api/analysis-batches/recovery-batch')return res.end(JSON.stringify(batch()));
 const detail=url.pathname.match(/^\/trajectory\/api\/sessions\/(recover|uncertain)\/analysis$/);
 if(detail&&req.method==='GET'){
  const id=detail[1];return res.end(JSON.stringify({session:sessions.find(s=>s.id===id),status:id==='recover'&&queued?'queued':'failed',coverage:{content_available:true},resume:resume(id),operations:[],tasks:[],message:id==='recover'?'Model operation coverage is incomplete or duplicated':'Jindu call result uncertain'}));
 }
 if(req.method==='POST'){
  posts.push({path:url.pathname,body:JSON.parse(body)});
  assert.equal(url.pathname,'/trajectory/api/analysis-jobs/job-recover/resume');
  if(failResume){res.writeHead(503);return res.end(JSON.stringify({message:'临时读取失败'}))}
  queued=true;return res.end(JSON.stringify({job_id:'job-recover',session_id:'recover',status:'queued',resume_generation:1,completed_chunks:8}));
 }
 if(url.pathname.endsWith('.svg')){res.setHeader('content-type','image/svg+xml');return res.end('<svg xmlns="http://www.w3.org/2000/svg"/>')}
 res.setHeader('content-type','text/html');res.end(html);
});
(async()=>{
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/trajectory/');
  await page.waitForSelector('[data-session-id="recover"]');
  await page.locator('[data-session-id="uncertain"]').click();
  await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('需要先核对 Jindu 回执'));
  assert.equal(await page.locator('#analyze-session').count(),0);
  assert.equal(await page.locator('#analysis-content [data-resume-job]').count(),0);
  assert.equal(posts.length,0);
  assert.equal(await page.locator('.batch-panel .progress > span').first().evaluate(n=>n.style.width),'0%');
  assert.equal(await page.locator('.batch-progress-failed').evaluate(n=>n.style.width),'100%');
  assert.match(await page.locator('.batch-panel [role=progressbar]').getAttribute('aria-valuetext'),/已完成 0，失败 2/);
  await page.locator('[data-session-id="recover"]').click();
  await page.waitForSelector('#analysis-content [data-resume-job="job-recover"]');
  assert.equal(await page.locator('#analyze-session').count(),0);
  assert((await analysisText(page)).includes('已保存 8 个窗口'));
  await page.locator('#analysis-content [data-resume-job]').click();
  await page.waitForFunction(()=>document.querySelector('#analysis-content .resume-feedback')?.textContent.includes('503'));
  assert.equal(await page.locator('#analysis-content [data-resume-job]').isEnabled(),true);
  if(!await page.locator('#batch-activity').evaluate(n=>n.open))await page.locator('#batch-activity > summary').click();
  assert.equal(await page.locator('.batch-panel [data-resume-job]').count(),1);
  assert((await page.locator('#batch-activity').innerText()).includes('系统不会自动重发'));
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:process.argv[3]+'/recovery-mobile.png',fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  failResume=false;await page.locator('.batch-panel [data-resume-job="job-recover"]').click();
  await page.waitForFunction(()=>document.querySelector('#analysis-job-state')?.textContent==='等待分析');
  assert.equal(posts.length,2);
  assert.deepEqual(posts[0],posts[1]);
  assert.match(posts[0].body.mutation_id,/^[0-9a-f-]{36}$/);
  assert.equal(Object.keys(posts[0].body).length,1);
  assert.equal(await page.locator('#analysis-content [data-resume-job]').count(),0);
  await page.reload();await page.waitForSelector('#batch-activity');
  assert.equal(posts.length,2);
  if(!await page.locator('#batch-activity').evaluate(n=>n.open))await page.locator('#batch-activity > summary').click();
  assert((await page.locator('#batch-activity').innerText()).includes('等待分析'));
  assert.deepEqual(errors,[]);
  console.log(JSON.stringify({status:'passed',checks:['server-authoritative resume eligibility','no new analysis after failure','uncertain blocks paid retry','saved prefix displayed','same mutation across detail and batch retry','batch identity retained','no model call from reload','mobile layout'],pageErrors:errors}));
 }finally{await browser.close();server.close()}
})().catch(error=>{console.error(error);process.exitCode=1;server.close()});

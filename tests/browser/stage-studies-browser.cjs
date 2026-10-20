// Fixture-only, real research assets. No credentials, persistent DB or model calls.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE);
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const source = path.dirname(process.argv[2]), output = process.argv[3];
const hostStyles = [...fs.readFileSync(process.argv[2],'utf8').matchAll(/<style>([\s\S]*?)<\/style>/g)].map(match=>match[0]).join('');
fs.mkdirSync(output, {recursive:true});
const names = ['understand_decide','build_execute','validate_debug','coordinate_maintain','uncertain'];
const distribution = {available:2,missing:1,mean:0.5,median:0.5,p90:0.9,min:0,max:1,sum:1,sample_sd:0.2,sample_variance:0.04};
const group = {stages:2,direct_operations:3,leaf_stages:1,direct_nonempty_stages:2,multiple_label_stages:1,multiple_label_rate:0.5,
 uncertain_rate:0,mixed_rate:0.5,confidence:distribution,mixed_probability:distribution,operation_count:distribution,
 subtree_operation_count:distribution,subtree_tag_entropy:distribution,metric:distribution};
const data = {study_id:'fixture-study',title:'Fixture study',revision:'fixture-revision',batch_id:'fixture-batch',
 summary:group,metric:'recorded_tokens',changed_analysis_sessions:[],unique_resource_metric:distribution,
 categories:names.map((tag,i)=>({...group,tag,name:['理解与决策','构建与执行','验证与纠错','协调与维护','待确认'][i],
  stages:i?0:2,stage_share:i?0:1,stage_share_ci95:i?[0,0]:[0.6,1],resource_share:i?0:1,resource_share_ci95:i?[0,0]:[0.4,1],
  label_coverage:i===1?0.5:i?0:1,session_stage_share_mean:0.5,session_stage_share_sd:0.1,session_stage_share_variance:0.01,
  session_resource_share_mean:0.4,session_resource_share_sd:0.2,session_resource_share_variance:0.04,resource_share_sessions:2})),
 by_depth:[{...group,depth:1},{...group,depth:2}],by_node_kind:[{...group,node_kind:'leaf'},{...group,node_kind:'parent'}],
 confidence_histogram:[0,0,0,0,0,1,0,0,0,1],depth_relations:Object.fromEntries(['mixed_probability','confidence'].map(k=>[k,{spearman_rho:-0.2,session_cluster_ci95:[-0.6,0.2]}])),
 confidence_threshold:0.5,secondary_threshold:0.2,resource_frontier_stages:1,classification:{model:'fixture-jev',route:'fixture-jindu'},
 uncertainty_method:'10000 session-cluster bootstrap, model errors excluded',limitations:['分段错误和模型错标未纳入区间。'],
 sessions:[{session_id:'fixture-session',title:'AI CPM 测试',started_at:'2026-10-20',analysis_revision:'analysis-v1',source_revision:'source-v1',segmentation:{model:'fixture-segmenter'}}]};
const item = {session_id:'fixture-session',task_id:'parent',title:'审查 <script>window.injected=true</script>',parent_id:'root',depth:1,is_leaf:false,
 effective_tag:'understand_decide',secondary_tags:['build_execute'],confidence:0.9,mixed_probability:0.8,operation_count:1,subtree_operation_count:3,
 probabilities:Object.fromEntries(names.map((k,i)=>[k,i?0:1])),subtree_tag_entropy:0.6,call_id:'fixture-call-id',receipt_id:'fixture-receipt',selected_metrics:{recorded_tokens:123}};
let mode='normal',delay=0;
const requests=[],errors=[];
const html=`<!doctype html><html lang="zh"><head><meta charset="utf-8">${hostStyles}<meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/research.css"></head><body><main id="research"></main><script src="/research.js"></script><script>
const request=async(url,options={})=>{const r=await fetch(url);if(!r.ok)throw Error('HTTP '+r.status);return options.responseType==='text'?r.text():r.json()};
window.ready=TrajectoryResearch.mount(document.querySelector('main'),{request}).catch(e=>{document.body.dataset.mountError=e.message});
</script></body></html>`;
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://fixture');requests.push({path:u.pathname,query:Object.fromEntries(u.searchParams),method:req.method});
 if(req.method!=='GET'){res.writeHead(405);return res.end();}
 if(u.pathname==='/research.js'||u.pathname==='/research.css'){res.setHeader('content-type',u.pathname.endsWith('.js')?'application/javascript; charset=utf-8':'text/css; charset=utf-8');return res.end(fs.readFileSync(path.join(source,u.pathname.slice(1))));}
 if(u.pathname==='/'){res.setHeader('content-type','text/html');return res.end(html);}
 res.setHeader('content-type','application/json');
 if(mode==='denied'){res.writeHead(403);return res.end('{}');}
 if(u.pathname==='/api/stage-studies')return res.end(JSON.stringify({items:mode==='empty'?[]:[{id:'fixture-study',title:'Fixture study'}]}));
 if(delay)await new Promise(resolve=>setTimeout(resolve,delay));
 if(mode==='error'){res.writeHead(503);return res.end('{}');}
 if(u.pathname.endsWith('/stages')){
  if(u.searchParams.get('format')==='csv'){res.setHeader('content-type','text/csv');return res.end('task_id,confidence\nparent,0.9\n');}
  return res.end(JSON.stringify({items:[item],total:1,next_offset:null}));
 }
 return res.end(JSON.stringify({...data,filters:Object.fromEntries(u.searchParams)}));
});
(async()=>{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const origin='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  delay=250;await page.goto(origin);await page.locator('.research-loading').waitFor();await page.waitForFunction(()=>document.querySelector('.research-app')?.getAttribute('aria-busy')==='false');delay=0;
  assert.match(await page.locator('main').innerText(),/方差（百分点²）/);
  const contrast = await page.evaluate(() => {
    const rgb = value => value.match(/[0-9.]+/g).slice(0,3).map(Number);
    const luminance = value => rgb(value).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4}).reduce((sum,v,i)=>sum+v*[0.2126,0.7152,0.0722][i],0);
    return ['.research-intro h2','.research-provenance>summary','.research-heading p','.research-columns>div>p'].map(selector=>{
      const node=document.querySelector(selector);let ancestor=node,bg='rgba(0, 0, 0, 0)';
      while(ancestor&&bg==='rgba(0, 0, 0, 0)'){bg=getComputedStyle(ancestor).backgroundColor;ancestor=ancestor.parentElement;}
      const a=luminance(getComputedStyle(node).color),b=luminance(bg);return {selector,ratio:(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05)};
    });
  });
  assert(contrast.every(item=>item.ratio>=4.5),JSON.stringify(contrast));
  assert.match(await page.locator('main').innerText(),/95%/);
  assert.match(await page.locator('main').innerText(),/多标签率/);
  assert.match(await page.locator('main').innerText(),/当前没有随机人工gold/);
  assert.equal(await page.evaluate(()=>window.injected),undefined);
  const select=async(label,value,key)=>{await page.getByLabel(label,{exact:true}).selectOption(value);await page.waitForFunction(()=>document.querySelector('.research-app')?.getAttribute('aria-busy')==='false');assert(requests.some(r=>r.query[key]===value));};
  await select('层级','2','depth');await select('节点','leaf','node_kind');await select('最低分类 confidence','0.8','confidence_min');await select('混合判断','single','mixed');
  await page.getByLabel('节点',{exact:true}).focus();await page.keyboard.press('ArrowUp');await page.keyboard.press('Enter');
  const downloadEvent=page.waitForEvent('download');await page.getByRole('button',{name:'导出筛选结果 CSV'}).click();const download=await downloadEvent;await download.saveAs(path.join(output,'fixture.csv'));assert.match(fs.readFileSync(path.join(output,'fixture.csv'),'utf8'),/parent,0.9/);
  mode='error';await page.getByLabel('层级',{exact:true}).selectOption('1');await page.getByRole('button',{name:'重试',exact:true}).waitFor();assert.match(await page.locator('.research-status').innerText(),/503/);mode='normal';await page.getByRole('button',{name:'重试',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.research-app')?.getAttribute('aria-busy')==='false');
  await page.screenshot({path:path.join(output,'research-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'research-mobile.png'),fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  mode='empty';await page.reload();await page.getByText('还没有导入的分段研究。',{exact:false}).waitFor();
  mode='denied';await page.reload();await page.waitForFunction(()=>document.body.dataset.mountError==='HTTP 403');assert.equal(await page.locator('.research-table').count(),0);
  assert.deepEqual(errors,[]);assert(requests.every(r=>r.method==='GET'));assert(!fs.readFileSync(path.join(source,'research.js'),'utf8').includes('\u00b7'));
  fs.writeFileSync(path.join(output,'result.json'),JSON.stringify({passed:true,checks:['loading','variance','intervals','mixed','depth','leaf','confidence','keyboard','csv','error-retry','mobile','empty','account-denied','no-writes','host-theme-contrast'],contrast,requests},null,2));
  console.log('PASS stage research browser, 15 checks');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;});

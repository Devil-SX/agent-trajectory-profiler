// Read-only acceptance against the deployed service. No response mocks or HAR.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),assert=require('node:assert/strict');
const auth=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const output=process.argv[3],base=new URL(auth.base_url);
const headers={Authorization:'Bearer '+auth.token},timings=[];
const title=session=>session.display_title||session.first_user_message||session.title||session.name||session.id;
const stamp=session=>Date.parse(session.started_at||session.last_activity_at||'')||Number.MAX_SAFE_INTEGER;

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1100}});
    const page=await context.newPage(),errors=[],mutations=[];
    let blockedTelemetry=0;
    context.setDefaultTimeout(90000);page.setDefaultNavigationTimeout(90000);
    page.on('pageerror',error=>errors.push(error.message));
    await context.route('**/*',async route=>{
      const request=route.request(),url=new URL(request.url());
      if(!['GET','HEAD','OPTIONS'].includes(request.method())){
        if(url.pathname==='/cdn-cgi/rum')blockedTelemetry++;
        else mutations.push(request.method()+' '+url.pathname);
        return route.abort();
      }
      const safe={...request.headers()};delete safe.authorization;
      if(url.origin===base.origin)safe.authorization=headers.Authorization;
      return route.continue({headers:safe});
    });
    const api=async path=>{
      const started=Date.now();
      const response=await context.request.get(new URL('/trajectory/api/'+path,base).href,{headers,timeout:90000});
      assert.equal(response.status(),200,'Authenticated real API did not return 200');
      const data=await response.json();
      timings.push({endpoint:path.startsWith('sessions?')||path==='sessions'?'sessions':'analysis',elapsed_ms:Date.now()-started});
      return data;
    };
    const healthResponse=await context.request.get(new URL('/trajectory/health',base).href,{headers,timeout:90000});
    assert.equal(healthResponse.status(),200);
    const health=await healthResponse.json();
    if(process.env.EXPECTED_VERSION)assert.equal(health.version,process.env.EXPECTED_VERSION);
    const listing=await api('sessions');
    assert(listing.sessions.length>0,'No synchronized real sessions');
    let detail,selected;
    const candidates=listing.sessions.filter(s=>s.has_analysis===true&&s.content_available!==false&&
      ['complete','partial'].includes(s.analysis_status)&&
      (!process.env.EXPECTED_SESSION_ID||s.id===process.env.EXPECTED_SESSION_ID)).sort((a,b)=>stamp(a)-stamp(b));
    for(const session of candidates.slice(0,20)){
      const candidate=await api('sessions/'+encodeURIComponent(session.id)+'/analysis');
      if(candidate.status!=='stale'&&candidate.tasks?.length&&candidate.operations?.length){detail=candidate;selected=session;break;}
    }
    assert(selected,'No completed real task analysis available yet for the requested scope');
    if(process.env.EXPECTED_TOKEN_COUNT)assert.equal(detail.session.metrics.recorded_tokens,Number(process.env.EXPECTED_TOKEN_COUNT));
    if(process.env.EXPECTED_TASKS)assert.equal(detail.tasks.length,Number(process.env.EXPECTED_TASKS));
    if(process.env.EXPECTED_OPERATIONS)assert.equal(detail.operations.length,Number(process.env.EXPECTED_OPERATIONS));
    await page.goto(new URL('/trajectory/',base).href);
    await page.waitForSelector('#session-status');
    // Clear inherited scope and let the authenticated server filter before pagination.
    await page.fill('#since','');await page.fill('#until','');
    await page.selectOption('#project','');
    const openSession=async(session,status='analyzed')=>{
      await page.selectOption('#session-status',status);
      await page.selectOption('#session-directory','');
      await page.fill('#session-search',session.id);
      await page.click('#sessions-refresh');
      const button=page.locator('[data-session-id='+JSON.stringify(session.id)+']');
      await button.waitFor({state:'visible'});
      await button.click();
    };
    await openSession(selected);
    assert.equal(await page.inputValue('#session-status'),'analyzed');
    await page.waitForSelector('#analysis-view .task-select');
    assert.equal(await page.locator('#analysis-view .task-select').count(),detail.tasks.length);
    assert.equal(await page.locator('.analysis-title').textContent(),title(detail.session));
    const summaryText=await page.locator('#analysis-content .analysis-summary').textContent();
    if(detail.session.metrics?.cost_status==='unknown')assert(summaryText.includes('未知'));
    if(typeof detail.session.metrics?.known_subtotal_usd==='number'&&detail.session.metrics.cost_status!=='unknown'){
      assert(summaryText.includes(detail.session.metrics.known_subtotal_usd.toLocaleString('zh-CN',{maximumFractionDigits:6})+' USD'));
    }
    if(process.env.EXPECTED_COLLECTION_STATUS){
      assert.equal(detail.coverage.collection.status,process.env.EXPECTED_COLLECTION_STATUS);
      assert.equal(detail.session.metrics.collection_status,process.env.EXPECTED_COLLECTION_STATUS);
      if(process.env.EXPECTED_COLLECTION_STATUS==='partial'){
        assert(summaryText.includes('已知小计'));
        assert((await page.locator('#analysis-content').textContent()).includes('用量采集尚未完成'));
      }
    }
    const refresh=page.getByRole('button',{name:'刷新分析',exact:true});
    assert.equal(await refresh.count(),1);await refresh.click();
    await page.waitForSelector('#analysis-view .task-select');
    await page.getByRole('button',{name:'分段时间线',exact:true}).click();
    assert(await page.locator('.timeline-segment').count()>0);
    await page.getByRole('button',{name:'开销火焰图',exact:true}).click();
    const frames=await page.locator('.flame-frame').count();
    assert(frames>0||(await page.locator('#analysis-view').textContent()).includes('没有可绘制'));
    await page.getByRole('button',{name:'任务层级',exact:true}).click();
    const operation=detail.operations.slice(0,100).find(op=>Number.isInteger(op.location?.byte_start)&&Number.isInteger(op.location?.byte_end));
    assert(operation,'No source-located operation in first evidence page');
    const rawButton=page.locator('.raw-evidence-button[data-operation-id='+JSON.stringify(operation.id)+']');
    await rawButton.locator('xpath=ancestor::details').locator('summary').click();
    const rawResponse=page.waitForResponse(response=>response.url().endsWith('/operations/'+encodeURIComponent(operation.id)+'/evidence'));
    await rawButton.click();
    const evidenceResponse=await rawResponse;assert.equal(evidenceResponse.status(),200);
    const evidence=await evidenceResponse.json();
    assert(evidence.available===true,'Original evidence not yet available for current source revision');
    assert(typeof evidence.text==='string'&&evidence.text.length>0);
    await page.waitForFunction(id=>Array.from(document.querySelectorAll('.raw-evidence-button')).find(button=>button.dataset.operationId===id)?.textContent==='重新读取原始记录',operation.id);
    await page.screenshot({path:output+'/semantic-live-desktop.png',fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:output+'/semantic-live-mobile.png',fullPage:true});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    let partialCollectionCheck={checked:false,reason:'no_content_available_session_with_partial_collection'};
    const partialSession=listing.sessions.find(s=>s.content_available===true&&s.collection?.status==='partial'&&s.id!==selected.id);
    if(partialSession){
      const partialDetail=await api('sessions/'+encodeURIComponent(partialSession.id)+'/analysis');
      assert.equal(partialDetail.coverage.collection.status,'partial');
      await page.setViewportSize({width:1440,height:1100});
      await openSession(partialSession,'all');
      await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('用量采集尚未完成'));
      assert((await page.locator('#analysis-content .analysis-summary').textContent()).includes('已知小计'));
      await page.screenshot({path:output+'/semantic-live-collection-partial.png',fullPage:true});
      partialCollectionCheck={checked:true,session_id:partialSession.id,collection:partialDetail.coverage.collection};
    }
    assert.deepEqual(errors,[]);assert.deepEqual(mutations,[]);
    await api('sessions');await api('sessions/'+encodeURIComponent(selected.id)+'/analysis');
    const summary={result:'passed',version:health.version,session_id:selected.id,session_title:title(detail.session),collection:detail.coverage.collection,partial_collection_check:partialCollectionCheck,api_timings:timings,origin:base.origin,checked_at:new Date().toISOString(),sessions:listing.sessions.length,tasks:detail.tasks.length,operations:detail.operations.length,flame_frames:frames,evidence_available:evidence.available,evidence_truncated:evidence.truncated,analysis_status:detail.status,read_only:true,blocked_telemetry_requests:blockedTelemetry,cost_status:detail.session.metrics?.cost_status,known_subtotal_usd:detail.session.metrics?.known_subtotal_usd,recorded_tokens:detail.session.metrics?.recorded_tokens,page_errors:errors};
    fs.writeFileSync(output+'/semantic-live-result.json',JSON.stringify(summary,null,2),{mode:0o600});
    console.log(JSON.stringify(summary));
  } finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});

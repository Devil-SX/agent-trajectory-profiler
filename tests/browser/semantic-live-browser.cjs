// Read-only acceptance against the deployed service. No response mocks or HAR.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('fs'),assert=require('node:assert/strict');
const auth=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
const output=process.argv[3],base=new URL(process.env.BASE_URL||auth.base_url);
const expectPending=process.env.EXPECTED_SOURCE_PENDING==='1';
const headers={Authorization:'Bearer '+auth.token},timings=[];
const title=session=>session.display_title||session.first_user_message||session.title||session.name||session.id;
const stamp=session=>Date.parse(session.started_at||session.last_activity_at||'')||Number.MAX_SAFE_INTEGER;
let stage='initializing',activePage;
const trace=(event,detail={})=>{stage=event;fs.appendFileSync(output+'/semantic-live-progress.jsonl',JSON.stringify({at:new Date().toISOString(),event,...detail})+'\n',{mode:0o600});};

(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROMIUM_PATH,args:['--no-sandbox','--disable-gpu']});
  try {
    const context=await browser.newContext({viewport:{width:1440,height:1100}});
    const page=await context.newPage(),errors=[],mutations=[];activePage=page;trace('browser:ready');
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
      const started=Date.now();trace('api:start',{endpoint:path});
      const response=await context.request.get(new URL('/trajectory/api/'+path,base).href,{headers,timeout:90000});
      trace('api:response',{endpoint:path,status:response.status(),elapsed_ms:Date.now()-started});
      assert.equal(response.status(),200,'Authenticated real API did not return 200');
      const data=await response.json();
      timings.push({endpoint:path.startsWith('analysis-batches')?'batch':path.startsWith('sessions?')||path==='sessions'?'sessions':'analysis',elapsed_ms:Date.now()-started});
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
      (['complete','partial'].includes(s.analysis_status)||(expectPending&&s.source_pending===true))&&
      (!process.env.EXPECTED_SESSION_ID||s.id===process.env.EXPECTED_SESSION_ID)).sort((a,b)=>stamp(a)-stamp(b));
    for(const session of candidates.slice(0,20)){
      const candidate=await api('sessions/'+encodeURIComponent(session.id)+'/analysis');
      if((candidate.status!=='stale'||(expectPending&&candidate.source_pending&&candidate.analysis_matches_parsed))&&candidate.tasks?.length&&candidate.operations?.length){detail=candidate;selected=session;break;}
    }
    assert(selected,'No completed real task analysis available yet for the requested scope');
    if(process.env.EXPECTED_TOKEN_COUNT)assert.equal(detail.session.metrics.recorded_tokens,Number(process.env.EXPECTED_TOKEN_COUNT));
    if(process.env.EXPECTED_TASKS)assert.equal(detail.tasks.length,Number(process.env.EXPECTED_TASKS));
    if(process.env.EXPECTED_OPERATIONS)assert.equal(detail.operations.length,Number(process.env.EXPECTED_OPERATIONS));
    trace('page:navigate');await page.goto(new URL('/trajectory/',base).href);trace('page:loaded');
    await page.waitForSelector('#session-status');
    // Clear inherited scope and let the authenticated server filter before pagination.
    await page.fill('#since','');await page.fill('#until','');
    await page.locator('#project').evaluate(e=>{e.value=''});
    const openSession=async(session,status='analyzed')=>{
      trace('session:filter',{session_id:session.id,status});await page.locator('#session-status').evaluate((e,value)=>{e.value=value},status);
      await page.locator('#session-directory').evaluate(e=>{e.value=''});
      const metadata=listing.sessions.find(s=>s.id===session.id)||session;
      const query=metadata.native_session_id||metadata.title||metadata.display_title||'';
      const filtered=page.waitForResponse(r=>{const u=new URL(r.url());return r.request().method()==='GET'&&u.pathname==='/trajectory/api/sessions'&&u.searchParams.get('q')===query&&u.searchParams.get('analysis_status')===status});
      await page.fill('#session-search',query);const filteredResponse=await filtered;assert.equal(filteredResponse.status(),200);
      await page.waitForFunction(()=>!document.querySelector('#sessions-refresh').disabled);
      const button=page.locator('[data-session-id='+JSON.stringify(session.id)+']');
      while(!await button.count()&&await page.locator('#sessions-more').isVisible()){await page.click('#sessions-more');await page.waitForFunction(()=>!document.querySelector('#sessions-more').disabled);}
      await button.waitFor({state:'visible'});trace('session:visible',{session_id:session.id,query});
      const observed=page.waitForResponse(r=>r.request().method()==='GET'&&new URL(r.url()).pathname.endsWith('/sessions/'+encodeURIComponent(session.id)+'/analysis'));
      await button.click();const response=await observed;trace('session:detail',{session_id:session.id,status:response.status()});assert.equal(response.status(),200);const shown=await response.json();
      await page.waitForFunction(expected=>document.querySelector('.analysis-title')?.textContent===expected,title(shown.session));return shown;
    };
    detail=await openSession(selected);
    assert.equal(await page.inputValue('#session-status'),'analyzed');
    await page.waitForSelector('#analysis-view .task-select');
    assert.equal(await page.locator('#analysis-view .task-select').count(),detail.tasks.length);
    assert.equal(await page.locator('.analysis-title').textContent(),title(detail.session));
    const summaryText=await page.locator('#analysis-content .analysis-summary').textContent();
    let interactionCheck={checked:false};
    if(process.env.EXPECTED_INTERACTION_UNAVAILABLE==='1'){
      const availability=detail.coverage?.interaction_availability;
      assert.equal(typeof availability==='object'?availability?.available:availability,false);
      assert.equal(detail.session.metrics.human_interactions,null);
      assert.equal(detail.session.metrics.human_input_chars,null);
      for(const label of ['人类交互次数','人类输入字数']){
        const card=page.locator('#analysis-content .analysis-summary .card').filter({has:page.locator('.card-label').filter({hasText:label})});
        assert((await card.locator('.value').textContent()).includes('未知'));
      }
      interactionCheck={checked:true,availability,human_interactions:null,human_input_chars:null};
    }
    let promptTitleCheck={checked:false};
    if(process.env.EXPECTED_EFFECTIVE_PROMPT==='1'){
      const first=detail.session.first_user_message,display=detail.session.display_title;
      assert(typeof first==='string'&&first.trim().length>0,'Missing original effective user question');
      assert(typeof display==='string'&&display.trim().length>0,'Missing effective display title');
      assert(!/^\s*#\s*AGENTS\b|<INSTRUCTIONS>|<environment_context>/i.test(first),'Instruction envelope used as effective user question');
      assert(!/^\s*#?\s*AGENTS\.md\b/i.test(display),'AGENTS file used as session display title');
      promptTitleCheck={checked:true,display_title:display,first_user_message:first};
    }
    trace('analysis:title_interaction_verified');

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
    const assertAnalysisCost=async(shown)=>{
      const provenance=shown.provenance||{},quote=shown.analysis_cost;
      const panel=page.locator('details').filter({has:page.locator('summary').filter({hasText:'本次分析调用与开销'})});
      if(!provenance.model&&!quote)return {checked:false,reason:'no_model_provenance'};
      assert.equal(await panel.count(),1);
      if(!await panel.evaluate(n=>n.open))await panel.locator('summary').click();
      const text=await panel.innerText();
      if(provenance.model)assert(text.includes('模型 '+provenance.model));
      const effort=provenance.reasoning_effort||provenance.effort;
      if(effort)assert(text.includes('推理强度 '+effort));
      if(quote){
        assert(text.includes('分析 API 等价成本'));
        assert.equal(quote.actual_charge,null);assert.equal(quote.actual_charge_currency,null);
        assert(text.includes('实际扣费未知'));
        if(quote.cost_status==='complete')assert(text.includes(quote.estimated_usd.toLocaleString('zh-CN',{maximumFractionDigits:6})+' USD'));
        if(quote.cost_status==='partial')assert(text.includes('已知小计，有计价缺口'));
        if(quote.cost_status==='unknown')assert(text.includes('分析 API 等价成本 未知'));
      }
      const calls=provenance.analysis_usage||[];
      if(calls.length){const visibleCalls=await panel.locator('tbody tr').count();if(['running','queued'].includes(shown.status))assert(visibleCalls>=calls.length);else assert.equal(visibleCalls,calls.length);}
      return {checked:true,model:provenance.model,reasoning_effort:effort,calls:calls.length,cost_status:quote?.cost_status,estimated_usd:quote?.estimated_usd,known_subtotal_usd:quote?.known_subtotal_usd,actual_charge:quote?.actual_charge};
    };
    if(process.env.EXPECTED_MODEL)assert.equal(detail.provenance?.model,process.env.EXPECTED_MODEL);
    if(process.env.EXPECTED_REASONING_EFFORT)assert.equal(detail.provenance?.reasoning_effort||detail.provenance?.effort,process.env.EXPECTED_REASONING_EFFORT);
    const analysisCostCheck=await assertAnalysisCost(detail);trace('analysis:cost_verified');
    let snapshotCheck={checked:false};
    if(expectPending){
      assert.equal(selected.source_pending,true);assert.equal(selected.analysis_current,false);
      assert.equal(detail.source_pending,true);assert.equal(detail.analysis_current,false);assert.equal(detail.analysis_matches_parsed,true);
      assert.equal(detail.analysis_source_revision,detail.source_revision);assert.notEqual(detail.current_source_revision,detail.source_revision);
      assert.equal(await page.locator('#analyze-session').count(),0);
      assert((await page.locator('#analysis-content').textContent()).includes('等待重新解析'));
      assert.equal(detail.session.metrics.input,null);assert(detail.tasks.every(task=>task.metrics.input===null));
      if(process.env.EXPECTED_ANALYSIS_COST_USD)assert(Math.abs((detail.analysis_cost?.estimated_usd??detail.analysis_cost?.known_subtotal_usd)-Number(process.env.EXPECTED_ANALYSIS_COST_USD))<1e-10);
      snapshotCheck={checked:true,source_pending:detail.source_pending,analysis_current:detail.analysis_current,analysis_matches_parsed:detail.analysis_matches_parsed,source_revision:detail.source_revision,current_source_revision:detail.current_source_revision,analysis_source_revision:detail.analysis_source_revision,execution_metrics_unknown:true,paid_analysis_button_absent:true};
    }
    const refresh=page.getByRole('button',{name:'刷新分析',exact:true});
    if(expectPending)assert.equal(await refresh.count(),0);else{assert.equal(await refresh.count(),1);await refresh.click();}
    await page.waitForSelector('#analysis-view .task-select');
    await page.getByRole('button',{name:'分段时间线',exact:true}).click();
    assert(await page.locator('.timeline-segment').count()>0);
    await page.getByRole('button',{name:'开销火焰图',exact:true}).click();
    const frames=await page.locator('.flame-frame').count();
    assert(frames>0||(await page.locator('#analysis-view').textContent()).includes('没有可绘制'));
    await page.getByRole('button',{name:'任务层级',exact:true}).click();trace('analysis:graphs_verified');
    const operation=detail.operations.slice(0,100).find(op=>process.env.EXPECTED_EVIDENCE_OPERATION_ID?op.id===process.env.EXPECTED_EVIDENCE_OPERATION_ID:Number.isInteger(op.location?.byte_start)&&Number.isInteger(op.location?.byte_end));
    assert(operation,'No source-located operation in first evidence page');
    const rawButton=page.locator('.raw-evidence-button[data-operation-id='+JSON.stringify(operation.id)+']');
    await rawButton.locator('xpath=ancestor::details').locator('summary').click();
    const rawResponse=page.waitForResponse(response=>response.url().endsWith('/operations/'+encodeURIComponent(operation.id)+'/evidence'));
    await rawButton.click();
    const evidenceResponse=await rawResponse;assert.equal(evidenceResponse.status(),200);
    const evidence=await evidenceResponse.json();
    assert(evidence.available===true,'Original evidence not yet available for current source revision');
    assert(typeof evidence.text==='string'&&evidence.text.length>0);
    if(expectPending){assert.equal(evidence.snapshot_current,false);assert.equal(evidence.source_revision,detail.source_revision);assert.equal(evidence.current_source_revision,detail.current_source_revision);}
    if(process.env.EXPECTED_EVIDENCE_START)assert.equal(evidence.byte_start,Number(process.env.EXPECTED_EVIDENCE_START));
    if(process.env.EXPECTED_EVIDENCE_END)assert.equal(evidence.byte_end,Number(process.env.EXPECTED_EVIDENCE_END));
    await page.waitForFunction(id=>Array.from(document.querySelectorAll('.raw-evidence-button')).find(button=>button.dataset.operationId===id)?.textContent==='重新读取原始记录',operation.id);
    trace('analysis:evidence_verified');await page.screenshot({path:output+'/semantic-live-desktop.png',fullPage:false});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:output+'/semantic-live-mobile.png',fullPage:false});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    let partialCollectionCheck={checked:false,reason:'no_content_available_session_with_partial_collection'};
    const partialSession=process.env.SKIP_PARTIAL_COLLECTION==='1'?null:listing.sessions.find(s=>s.content_available===true&&s.collection?.status==='partial'&&s.id!==selected.id);
    if(partialSession){
      const partialDetail=await api('sessions/'+encodeURIComponent(partialSession.id)+'/analysis');
      assert.equal(partialDetail.coverage.collection.status,'partial');
      await page.setViewportSize({width:1440,height:1100});
      await openSession(partialSession,'all');
      await page.waitForFunction(()=>document.querySelector('#analysis-content')?.textContent.includes('用量采集尚未完成'));
      assert((await page.locator('#analysis-content .analysis-summary').textContent()).includes('已知小计'));
      await page.screenshot({path:output+'/semantic-live-collection-partial.png',fullPage:false});
      partialCollectionCheck={checked:true,session_id:partialSession.id,collection:partialDetail.coverage.collection};
    }
    let recoveryCheck={checked:false,reason:'no_batch_available'};
    let batchProgressCheck={checked:false,reason:'no_batch_available'},runningCostCheck={checked:false,reason:'no_running_task_with_model_usage'};
    const batchListing=await api('analysis-batches');
    const batch=(batchListing.batches||[]).find(b=>!process.env.EXPECTED_BATCH_ID||b.batch_id===process.env.EXPECTED_BATCH_ID);
    if(process.env.EXPECTED_BATCH_ID)assert(batch,'Expected real batch not found');
    if(batch){
      const panel=page.locator('.batch-panel');await panel.waitFor();
      const details=panel.locator('details');if(!await details.evaluate(n=>n.open))await details.locator('summary').click();
      // The UI automatically selects the newest visible account batch.
      const visible=(batchListing.batches||[])[0];
      for(const item of visible.items||[]){
        if(item.session?.display_title)assert((await panel.innerText()).includes(item.session.display_title));
      }
      const aria=await panel.locator('[role=progressbar]').getAttribute('aria-valuetext');
      const counts=/已完成 ([\d,]+)，失败 ([\d,]+)，共 ([\d,]+)/.exec(aria||'');
      assert(counts,'Batch must distinguish complete and failed counts');
      const finished=Number(counts[1].replaceAll(',','')),failed=Number(counts[2].replaceAll(',','')),total=Number(counts[3].replaceAll(',',''));
      const green=await panel.locator('.batch-progress-complete').evaluate(n=>parseFloat(n.style.width));
      const red=await panel.locator('.batch-progress-failed').evaluate(n=>({width:parseFloat(n.style.width),color:getComputedStyle(n).backgroundColor}));
      assert(Math.abs(green-(total?finished/total*100:0))<0.01);
      assert(Math.abs(red.width-(total?failed/total*100:0))<0.01);
      const rgb=red.color.match(/[\d.]+/g).map(Number);assert(rgb[0]>rgb[1]+20&&rgb[0]>rgb[2]+20,'Failure segment must be red');
      let eligibleVisible=0,uncertainVisible=0,transitioned=0;
      for(const [index,item] of (visible.items||[]).entries()){
        if(item.status!=='failed')continue;
        const row=panel.locator('.batch-item').nth(index);
        if(!(await row.innerText()).includes('分析失败')){transitioned++;continue;}
        if(item.resume?.eligible){assert.equal(await row.locator('[data-resume-job='+JSON.stringify(item.resume.job_id)+']').count(),1);eligibleVisible++;}
        if(item.resume?.reason==='prior_call_uncertain'){assert.equal(await row.locator('[data-resume-job]').count(),0);assert((await row.innerText()).includes('系统不会自动重发'));uncertainVisible++;}
      }
      recoveryCheck={checked:true,failed_in_live_batch:failed,eligible_resume_buttons_observed:eligibleVisible,uncertain_blocked_observed:uncertainVisible,transitioned_during_check:transitioned,failed_segment_color:red.color,button_clicked:false,uncovered:failed===0?'No real failed sample after authorized recovery; red failure and uncertain-button behavior covered by isolated recovery fixture':null};
      const running=process.env.SKIP_RUNNING_DETAIL==='1'?null:(batch.items||[]).find(i=>['running','queued'].includes(i.status)&&i.progress?.analysis_usage?.length);
      if(running){
        const shown=await openSession({id:running.session_id},'all');
        if(shown.progress?.analysis_usage?.length||shown.provenance?.analysis_usage?.length){
          runningCostCheck={...await assertAnalysisCost(shown),session_id:running.session_id,status:shown.status,progress:shown.progress?{completed_chunks:shown.progress.completed_chunks,total_chunks:shown.progress.total_chunks}:null};
          await page.screenshot({path:output+'/semantic-live-running-cost.png',fullPage:false});
        }
      }
      batchProgressCheck={checked:true,batch_id:batch.batch_id,status:batch.status,total:batch.total,counts:batch.counts};
    }
    assert.deepEqual(errors,[]);assert.deepEqual(mutations,[]);
    if(process.env.REPEAT_READ_TIMINGS==='1'){await api('sessions');await api('sessions/'+encodeURIComponent(selected.id)+'/analysis');}
    const summary={result:'passed',version:health.version,session_id:selected.id,session_title:title(detail.session),collection:detail.coverage.collection,partial_collection_check:partialCollectionCheck,load_control:{skip_partial_collection:process.env.SKIP_PARTIAL_COLLECTION==='1',skip_running_detail:process.env.SKIP_RUNNING_DETAIL==='1',repeat_reads:process.env.REPEAT_READ_TIMINGS==='1'},analysis_cost_check:analysisCostCheck,snapshot_check:snapshotCheck,evidence_snapshot_current:evidence.snapshot_current,evidence_byte_start:evidence.byte_start,evidence_byte_end:evidence.byte_end,interaction_check:interactionCheck,effective_prompt_check:promptTitleCheck,batch_progress_check:batchProgressCheck,recovery_check:recoveryCheck,running_cost_check:runningCostCheck,api_timings:timings,origin:base.origin,checked_at:new Date().toISOString(),sessions:listing.sessions.length,tasks:detail.tasks.length,operations:detail.operations.length,flame_frames:frames,evidence_available:evidence.available,evidence_truncated:evidence.truncated,analysis_status:detail.status,read_only:true,blocked_telemetry_requests:blockedTelemetry,cost_status:detail.session.metrics?.cost_status,known_subtotal_usd:detail.session.metrics?.known_subtotal_usd,recorded_tokens:detail.session.metrics?.recorded_tokens,page_errors:errors};
    fs.writeFileSync(output+'/semantic-live-result.json',JSON.stringify(summary,null,2),{mode:0o600});
    trace('acceptance:passed');console.log(JSON.stringify(summary));
  } catch(error){trace('acceptance:failed',{failed_stage:stage,message:error.message,timings});if(activePage&&!activePage.isClosed()){try{await activePage.screenshot({path:output+'/semantic-live-failure.png',fullPage:false,timeout:10000});}catch{}}throw error;} finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});

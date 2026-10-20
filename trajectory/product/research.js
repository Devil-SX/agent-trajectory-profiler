/* One authenticated study API for the website and Agents. No client-side cost model. */
window.TrajectoryResearch = (() => {
  const names = {understand_decide:'理解与决策',build_execute:'构建与执行',validate_debug:'验证与纠错',coordinate_maintain:'协调与维护',uncertain:'待确认'};
  const metrics = {recorded_tokens:'归一化记录 token',output:'输出 token',calls:'模型用量记录数',active_seconds_estimate:'活跃时间估计（秒）',tool_seconds:'工具累计时间（秒）',known_subtotal_usd:'参考费用已知小计（USD）',wall_span_seconds:'直接事件首末跨度（秒）',prompt_buckets:'对话请求分组数',human_interactions:'人类交互数',human_input_chars:'人类输入字数'};
  const palette = ['#4a78a8','#4c9880','#c57f50','#9071b0','#9ca4ad'];
  const num = (value,digits=1) => value === null || value === undefined ? '未知' : Number(value).toLocaleString('zh-CN',{maximumFractionDigits:digits});
  const pct = value => value === null || value === undefined ? '未知' : `${(value*100).toFixed(1)}%`;
  const duration = value => value===null||value===undefined?'未知':value>=3600?`${num(value/3600)} 小时`:value>=60?`${num(value/60)} 分钟`:`${num(value)} 秒`;
  const interval = value => value ? `${pct(value[0])}–${pct(value[1])}` : '样本不足';
  const el = (tag,text,cls) => {const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
  const heading = (title,note) => {const box=el('div',undefined,'research-heading');box.append(el('h3',title));if(note)box.append(el('p',note));return box;};
  function select(label,options,value,onchange){const wrap=el('label',undefined,'research-filter');wrap.append(el('span',label));const input=el('select');input.setAttribute('aria-label',label);for(const [key,text] of options){const option=el('option',text);option.value=key;input.append(option);}input.value=value||'';input.onchange=()=>onchange(input.value);wrap.append(input);return wrap;}
  function table(headers,rows){const wrap=el('div',undefined,'research-table-wrap');const node=el('table',undefined,'research-table');const head=el('thead'),hr=el('tr');for(const h of headers)hr.append(el('th',h));head.append(hr);node.append(head);const body=el('tbody');for(const row of rows){const tr=el('tr');for(const cell of row){const td=el('td');if(cell instanceof Node)td.append(cell);else td.textContent=String(cell);tr.append(td);}body.append(tr);}node.append(body);wrap.append(node);return wrap;}
  function confidenceHistogram(counts){const max=Math.max(1,...counts);const box=el('div',undefined,'research-hist');counts.forEach((count,i)=>{const col=el('div',undefined,'research-hist-column');const bar=el('div',undefined,'research-hist-bar');bar.style.height=`${Math.max(0,count/max*85)}px`;bar.title=`${(i/10).toFixed(1)}–${((i+1)/10).toFixed(1)}，${count}阶段`;col.append(el('strong',String(count)),bar,el('span',`${(i/10).toFixed(1)}`));box.append(col);});return box;}
  function forest(categories,kind,{spread=false}={}){const box=el('div',undefined,'research-forest');categories.forEach((category,i)=>{const value=category[`${kind}_share`],ci=category[`${kind}_share_ci95`];const row=el('div',undefined,'research-forest-row');row.append(el('span',category.name,'research-tag-name'));const track=el('div',undefined,'research-track');if(value!==null){const fill=el('div',undefined,'research-fill');fill.style.width=`${Math.max(0,Math.min(100,value*100))}%`;fill.style.background=palette[i];track.append(fill);}if(ci){const whisker=el('div',undefined,'research-whisker');whisker.style.left=`${ci[0]*100}%`;whisker.style.width=`${(ci[1]-ci[0])*100}%`;track.append(whisker);}row.append(track,el('strong',pct(value)),el('span',interval(ci),'research-ci'));if(spread)row.append(el('span',`记录间 SD ${category.session_resource_share_sd===null?'未知':num(category.session_resource_share_sd*100)+' 个百分点'}`,'research-spread'));box.append(row);});return box;}
  async function mount(container,{request}){
    container.replaceChildren();const app=el('div',undefined,'research-app');container.append(app);
    const listed=await request('/api/stage-studies');
    if(!listed.items.length){app.append(heading('研究统计','还没有导入的分段研究。'));return;}
    const state={study:listed.items[0].id,session_id:'',depth:'',node_kind:'all',tag:'',membership:'direct',metric:'recorded_tokens',confidence_min:'',mixed:'all',q:'',offset:0};
    const banner=el('div',undefined,'research-intro');banner.append(el('h2','阶段与分段研究'),el('p','比较活动开销，也检验分段粒度、混合程度与不确定性。'));
    const controls=el('div',undefined,'research-filters'),status=el('div',undefined,'research-status');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    const content=el('div',undefined,'research-content'),stageDrawer=el('details',undefined,'research-panel research-stage-drawer'),stageSummary=el('summary','阶段明细'),details=el('div');stageDrawer.append(stageSummary,details);app.append(banner,controls,status,content,stageDrawer);
    let serial=0,sessions=[],depths=[],advancedOpen=false,stagesDirty=true;
    stageDrawer.ontoggle=()=>{if(stageDrawer.open&&stagesDirty)void loadStages();};
    controls.addEventListener('keydown',event=>{if(event.key==='Escape'){const drawer=controls.querySelector('.research-filter-disclosure');if(drawer){advancedOpen=false;drawer.open=false;drawer.querySelector('summary').focus();}}});
    app.addEventListener('pointerdown',event=>{if(!controls.contains(event.target)){const drawer=controls.querySelector('.research-filter-disclosure');if(drawer){advancedOpen=false;drawer.open=false;}}});
    const parameters=()=>new URLSearchParams(Object.entries(state).filter(([key,value])=>!['study','offset'].includes(key)&&value!==''));
    const root=()=>`/api/stage-studies/${encodeURIComponent(state.study)}`;
    function update(key,value){advancedOpen=false;const drawer=controls.querySelector('.research-filter-disclosure');if(drawer)drawer.open=false;state[key]=value;state.offset=0;void load();}
    function renderFilters(){
      controls.replaceChildren();
      controls.append(
        select('研究批次',listed.items.map(item=>[item.id,item.title]),state.study,value=>update('study',value)),
        select('资源指标',Object.entries(metrics),state.metric,value=>update('metric',value))
      );
      const active=Object.entries(state).filter(([key,value])=>!['study','metric','offset'].includes(key)&&value!==''&&!(['node_kind','mixed'].includes(key)&&value==='all')&&!(key==='membership'&&value==='direct'));
      const drawer=el('details',undefined,'research-filter-disclosure');drawer.open=advancedOpen;
      drawer.ontoggle=()=>{advancedOpen=drawer.open;};
      drawer.append(el('summary',active.length?`筛选（${active.length}）`:'筛选'));
      const fields=el('div',undefined,'research-filter-fields');fields.append(
        select('会话',[['','全部会话'],...sessions.map(item=>[item.session_id,`${item.started_at?.slice(0,10)||'日期未知'} ${item.title||item.cwd||item.session_id}`])],state.session_id,value=>update('session_id',value)),
        select('层级',[['','全部层级'],...depths.map(depth=>[String(depth),`第 ${depth} 层`])],state.depth,value=>update('depth',value)),
        select('节点',[['all','全部节点'],['leaf','叶节点'],['parent','父节点']],state.node_kind,value=>update('node_kind',value)),
        select('活动标签',[['','全部标签'],...Object.entries(names)],state.tag,value=>update('tag',value)),
        select('指标归属',[['direct','直接操作'],['subtree','子树聚合']],state.membership,value=>update('membership',value)),
        select('最低分类 confidence',[['','不限'],['0.5','0.5'],['0.8','0.8'],['0.95','0.95']],state.confidence_min,value=>update('confidence_min',value)),
        select('混合判断',[['all','全部'],['mixed','混合概率 ≥ 0.5'],['single','混合概率 < 0.5']],state.mixed,value=>update('mixed',value))
      );
      const search=el('label',undefined,'research-filter');search.append(el('span','阶段搜索'));
      const input=el('input');input.type='search';input.setAttribute('aria-label','阶段搜索');input.placeholder='阶段名称或 ID';input.value=state.q;input.onchange=()=>update('q',input.value);search.append(input);fields.append(search);drawer.append(fields);controls.append(drawer);
      if(active.length){
        const chips=el('div',undefined,'research-active-filters');
        const labels={session_id:'会话',depth:'层级',node_kind:'节点',tag:'活动',membership:'归属',confidence_min:'confidence ≥',mixed:'混合判断',q:'搜索'};
        const values={leaf:'叶节点',parent:'父节点',subtree:'子树聚合',mixed:'混合',single:'较单一'};
        for(const [key,value] of active){
          const text=key==='session_id'?(sessions.find(item=>item.session_id===value)?.title||value):names[value]||values[value]||value;
          const chip=el('button',`${labels[key]}：${text} ×`,'research-filter-chip');chip.type='button';chip.title='移除此筛选';chip.onclick=()=>update(key,['node_kind','mixed'].includes(key)?'all':key==='membership'?'direct':'');chips.append(chip);
        }
        controls.append(chips);
      }
    }
    function disclosure(title,...children){
      const node=el('details',undefined,'research-disclosure');node.append(el('summary',title));
      const body=el('div',undefined,'research-disclosure-body');body.append(...children);node.append(body);return node;
    }
    function depthChart(groups){
      const chart=el('div',undefined,'research-depth-chart');
      const legend=el('p','橙色为模型混合率，绿色为多标签率。两者分别衡量混合判断与标签覆盖，不代表准确率。','research-note');chart.append(legend);
      for(const group of groups){
        const row=el('button',undefined,'research-depth-row');row.type='button';row.title=`筛选第 ${group.depth} 层`;row.onclick=()=>update('depth',String(group.depth));
        row.append(el('span',`第 ${group.depth} 层`),el('span',`${num(group.stages,0)} 阶段`,'research-depth-count'));
        for(const [key,name] of [['mixed_rate','混合'],['multiple_label_rate','多标签']]){
          const cell=el('span',undefined,'research-depth-value'),track=el('span',undefined,'research-depth-track'),fill=el('span',undefined,`research-depth-fill ${key}`);
          fill.style.width=`${Math.max(0,Math.min(100,(group[key]||0)*100))}%`;track.append(fill);cell.append(track,el('strong',pct(group[key])));cell.setAttribute('aria-label',`${name} ${pct(group[key])}`);row.append(cell);
        }
        chart.append(row);
      }
      return chart;
    }
    function renderSummary(data,timeData){content.replaceChildren();const s=data.summary;stageSummary.textContent=`阶段明细，${num(s.stages,0)} 个阶段`;const cards=el('div',undefined,'research-cards');for(const [label,value] of [['阶段',num(s.stages,0)],['叶节点 / 父节点',`${num(s.leaf_stages,0)} / ${num(s.stages-s.leaf_stages,0)}`],['待确认',pct(s.uncertain_rate)],['模型判为混合',pct(s.mixed_rate)],['已知资源小计',num(data.unique_resource_metric.sum,state.metric==='known_subtotal_usd'?4:1)],['资源缺口',`${data.unique_resource_metric.missing} 个归属单元`]]){const card=el('div',undefined,'research-card');card.append(el('span',label),el('strong',value));cards.append(card);}content.append(cards);
      if(data.changed_analysis_sessions.length)content.append(el('p',`${data.changed_analysis_sessions.length} 个会话的当前分析已更新，这里仍展示固定版本的研究快照。`,'research-warning'));
      const shares=el('section',undefined,'research-panel');shares.append(heading('工作分布与统计区间','95%区间按导入会话记录重采样，同源复制和 fork 依赖未校正，仅用于探索。'));
      const grids=el('div',undefined,'research-columns research-share-grid');const stages=el('div');stages.append(el('h4','互斥主标签的阶段占比'),el('p',`${data.categories[0]?.stage_share_sessions||0} 个会话记录，${num(data.summary.stages,0)} 个阶段`,'research-note'),forest(data.categories,'stage'));const resources=el('div');resources.append(el('h4',`${metrics[state.metric]}占比`),el('p',`${data.categories[0]?.resource_share_sessions||0} 个有效会话记录，${data.unique_resource_metric.available} 个归属单元有值，${data.unique_resource_metric.missing} 个未知。`,'research-note'),forest(data.categories,'resource'));if(state.metric==='active_seconds_estimate')grids.classList.add('research-share-two');grids.append(stages);if(state.metric!=='active_seconds_estimate')grids.append(resources);const time=el('div',undefined,'research-time-distribution');time.append(el('h4','活跃时间估计占比'),el('p',`总时长 ${duration(timeData.unique_resource_metric.sum)}${timeData.unique_resource_metric.sum!==null&&timeData.unique_resource_metric.sum>=60?`，${num(timeData.unique_resource_metric.sum)} 秒`:''}`,'research-time-total'),forest(timeData.categories,'resource',{spread:true}),el('p',`${timeData.categories[0]?.resource_share_sessions||0} 个有效会话记录，${timeData.unique_resource_metric.available} 个归属单元有值，${timeData.unique_resource_metric.missing} 个未知。`,'research-note'));if(timeData.unique_resource_metric.sum===0)time.append(el('p','已知总时长为零，无法计算占比或占比区间。','research-note'));grids.append(time);shares.append(grids);
      shares.append(disclosure('会话差异、方差与多标签覆盖',table(['活动','阶段数','含次标签覆盖率','记录占比均值 ± SD','记录占比方差（百分点²）','资源记录占比均值 ± SD','资源占比方差（百分点²）','资源有效记录数'],data.categories.map(c=>[c.name,num(c.stages,0),pct(c.label_coverage),`${pct(c.session_stage_share_mean)} ± ${pct(c.session_stage_share_sd)}`,num(c.session_stage_share_variance===null?null:c.session_stage_share_variance*10000,2),`${pct(c.session_resource_share_mean)} ± ${pct(c.session_resource_share_sd)}`,num(c.session_resource_share_variance===null?null:c.session_resource_share_variance*10000,2),num(c.resource_share_sessions,0)]))));
      const activeRule=timeData.measurement_policy?.active_time;shares.append(el('p',`${activeRule&&activeRule.includes('1800')?'本研究按相邻事件间隔估计，最长30分钟，排除以请求结束的间隔。':'活跃时间来自保存的事件间隔估计，计时规则见方法信息。'}它不是真实 LLM 请求延时，也不代表人工工时。`,'research-note'));
      if(state.metric==='tool_seconds')shares.append(el('p','工具累计时间可能因并发重叠，不能与活跃时间相加或作为墙钟时长。','research-note'));
      if(state.metric==='wall_span_seconds')shares.append(el('p','事件首末跨度包含等待和任务交错，不是独占处理时间。','research-note'));
      shares.append(el('p',state.membership==='subtree'?`子树逐行可能重叠，资源总量只计 ${data.resource_frontier_stages} 个无重叠选中祖先。资源按这些祖先的主标签归属。`:'资源按阶段的直接操作唯一归属，父节点不重复包含子节点开销。','research-note'));

      shares.append(el('p','活动筛选同时匹配主标签和次标签；各类含次标签覆盖率可合计超过100%。未知资源不计入已知小计或占比分母。','research-note'));content.append(shares);
      const quality=el('section',undefined,'research-panel');quality.append(heading('分段结构与混合程度','检验层级关系，不预设更细的阶段一定更单一。父节点的子树标签多样性与当前阶段的模型混合判断分别展示。'));
      const plots=el('div',undefined,'research-columns');const histogram=el('div');histogram.append(el('h4','分类模型 confidence 分布'),confidenceHistogram(data.confidence_histogram),el('p',`待确认阈值 ${num(data.confidence_threshold,2)}，次标签概率阈值 ${num(data.secondary_threshold,2)}。分段模型没有提供可用的逐阶段confidence；当前没有随机人工gold。`,'research-note'));
      const relations=el('div');relations.append(el('h4','深度与活动特征的关联'));for(const [key,label] of [['mixed_probability','混合概率'],['confidence','分类confidence']]){const r=data.depth_relations[key];relations.append(el('p',`${label}，Spearman ρ = ${num(r.spearman_rho,3)}，记录聚类95%区间（探索性） ${r.session_cluster_ci95?r.session_cluster_ci95.map(x=>num(x,3)).join(' 至 '):'样本不足'}`));}relations.append(el('p','深度关联是探索性结果，受到父子依赖、项目和阶段长度影响；不等于因果或分类准确率。','research-note'));plots.append(histogram,relations);quality.append(depthChart(data.by_depth));
      quality.append(el('p','模型confidence尚未校准，不能理解为正确概率。当前分段置信度与人工准确率未知。','research-note'));
      const diagnostics=disclosure('层级明细、模型置信度与关联检验',plots);
      diagnostics.lastElementChild.append(table(['层级','阶段 / 叶节点','直接操作量中位数 / P90','子树操作量中位数','confidence中位数','待确认率','模型混合率','多标签率','混合概率均值 ± SD','子树标签熵均值'],data.by_depth.map(g=>[g.depth,`${g.stages} / ${g.leaf_stages}`,`${num(g.operation_count.median)} / ${num(g.operation_count.p90)}`,num(g.subtree_operation_count.median),num(g.confidence.median,2),pct(g.uncertain_rate),pct(g.mixed_rate),pct(g.multiple_label_rate),`${num(g.mixed_probability.mean,2)} ± ${num(g.mixed_probability.sample_sd,2)}`,num(g.subtree_tag_entropy.mean,2)])));
      diagnostics.lastElementChild.append(table(['节点类型','阶段数','直接操作数','有直接操作的阶段','模型混合率','多标签率','confidence中位数','指标可用 / 缺失','指标中位数 / P90'],data.by_node_kind.map(g=>[g.node_kind==='leaf'?'叶节点':'父节点',g.stages,num(g.direct_operations,0),num(g.direct_nonempty_stages,0),pct(g.mixed_rate),pct(g.multiple_label_rate),num(g.confidence.median,2),`${g.metric.available} / ${g.metric.missing}`,`${num(g.metric.median)} / ${num(g.metric.p90)}`])));quality.append(diagnostics);content.append(quality);
      const provenance=el('details',undefined,'research-provenance');provenance.append(el('summary','方法、版本与已知缺口'));const p=el('div');p.append(el('p',`分类模型 ${data.classification.model||'未提供'}，路由 ${data.classification.route||'未提供'}。本页读取不调用模型。`),el('p',data.uncertainty_method),el('p',`活跃时间计时规则：${timeData.measurement_policy?.active_time||'未提供'}`),el('p',`资源覆盖规则：${timeData.resource_coverage_policy||'未提供'}`),el('p',`研究 revision：${data.revision}`));for(const note of data.limitations)p.append(el('p',note));p.append(table(['会话','分段模型 / 方法','分析版本','源版本'],data.sessions.map(s=>[s.title||s.session_id,`${s.segmentation.model||'未知'} / ${s.segmentation.prompt_version||s.segmentation.backend||'未知'}`,s.analysis_revision,s.source_revision])));provenance.append(p);content.append(provenance);
    }
    async function renderStages(epoch){const query=parameters();query.set('limit','25');query.set('offset',String(state.offset));const rows=await request(`${root()}/stages?${query}`);if(epoch!==serial)return;details.replaceChildren();details.append(heading('阶段明细',`${rows.total} 个匹配阶段，保留原任务名称与版本。展开查看调用回执和多标签概率。`));const exportButton=el('button','导出筛选结果 CSV','research-button');exportButton.type='button';exportButton.onclick=async()=>{exportButton.disabled=true;try{const q=parameters();q.set('format','csv');const csv=await request(`${root()}/stages?${q}`,{responseType:'text'});const blob=new Blob([csv],{type:'text/csv;charset=utf-8'});const url=URL.createObjectURL(blob);const a=el('a');a.href=url;a.download='trajectory-stage-study.csv';a.click();URL.revokeObjectURL(url);}catch(error){status.textContent=`导出失败：${error.message}`;}finally{exportButton.disabled=false;}};details.append(exportButton);
      details.append(table(['阶段','层级 / 类型','主标签与次标签','confidence / 混合概率','直接 / 子树操作','资源指标'],rows.items.map(row=>{const description=el('details');description.append(el('summary',row.title));const box=el('div',undefined,'research-stage-provenance');for(const [label,value] of [['任务ID',row.task_id],['父任务',row.parent_id],['会话',row.session_id],['Jindu call ID',row.call_id],['Jindu receipt',row.receipt_id],['类别概率',Object.entries(row.probabilities).map(([k,v])=>`${names[k]} ${pct(v)}`).join('，')],['子树标签熵',num(row.subtree_tag_entropy,3)]])box.append(el('p',`${label}：${value}`));description.append(box);return [description,`${row.depth} / ${row.is_leaf?'叶':'父'}`,[names[row.effective_tag],...row.secondary_tags.map(t=>`${names[t]}（次）`)].join('，'),`${num(row.confidence,2)} / ${num(row.mixed_probability,2)}`,`${row.operation_count} / ${row.subtree_operation_count}`,num(row.selected_metrics[state.metric],state.metric==='known_subtotal_usd'?4:1)];})));
      const pager=el('div',undefined,'research-pagination');const prev=el('button','上一页','research-button'),next=el('button','下一页','research-button');prev.type=next.type='button';prev.disabled=state.offset===0;next.disabled=rows.next_offset===null;prev.onclick=()=>{state.offset=Math.max(0,state.offset-25);void loadStages();};next.onclick=()=>{state.offset=rows.next_offset;void loadStages();};pager.append(prev,el('span',`${Math.floor(state.offset/25)+1} / ${Math.max(1,Math.ceil(rows.total/25))}`),next);details.append(pager);}
    async function loadStages(){const epoch=serial;details.setAttribute('aria-busy','true');details.replaceChildren(el('p','正在读取阶段明细…','research-note research-loading'));status.textContent='正在读取阶段明细…';try{await renderStages(epoch);if(epoch===serial){stagesDirty=false;status.textContent='';}}catch(error){if(epoch===serial){status.dataset.state='error';status.textContent=`明细加载失败：${error.message}`;const retry=el('button','重试明细','research-button');retry.onclick=()=>void loadStages();details.replaceChildren(el('p',status.textContent,'research-error'),retry);}}finally{if(epoch===serial)details.setAttribute('aria-busy','false');}}
    async function load(initial=false){const epoch=++serial;app.setAttribute('aria-busy','true');content.dataset.stale='true';delete status.dataset.state;if(stageDrawer.open)details.replaceChildren(el('p','正在更新阶段明细…','research-note research-loading'));status.textContent='正在汇总分段研究…';status.classList.add('research-loading');try{const query=parameters(),timeQuery=new URLSearchParams(query);timeQuery.set('metric','active_seconds_estimate');const dataRead=request(`${root()}?${query}`);const [data,timeData]=await Promise.all([dataRead,state.metric==='active_seconds_estimate'?dataRead:request(`${root()}?${timeQuery}`)]);if(data.revision!==timeData.revision)throw Error('研究版本在读取期间变化，请重试');if(epoch!==serial)return;sessions=data.sessions;if(!state.depth)depths=data.by_depth.map(g=>g.depth);renderFilters();renderSummary(data,timeData);delete content.dataset.stale;stagesDirty=true;if(stageDrawer.open){await renderStages(epoch);stagesDirty=false;}else details.replaceChildren();if(epoch===serial)status.textContent=data.summary.stages?'':'没有符合筛选条件的阶段。';}catch(error){if(epoch===serial){status.dataset.state='error';status.textContent=`研究统计加载失败：${error.message}`;const retry=el('button','重试','research-button');retry.type='button';retry.onclick=()=>void load();status.append(retry);}if(initial)throw error;}finally{if(epoch===serial){app.setAttribute('aria-busy','false');status.classList.remove('research-loading');}}}
    renderFilters();await load(true);
  }
  return {mount};
})();

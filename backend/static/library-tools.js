// 浏览偏好属于界面；更新、收藏和结果始终读取 SQLite。
const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];
const STATUS = {idle:'尚未开始',pending:'等待更新',starting:'准备中',running:'正在更新',stopping:'正在停止',completed:'已完成',stopped:'已停止',failed:'未完成',needs_attention:'需要处理',interrupted:'上次中断',retrying:'正在重试'};
const FILTERS = {q:'searchInput',studio:'studioFilter',series:'seriesFilter',actress:'actressFilter',source:'sourceFilter',has_magnet:'magnetFilter',date_from:'dateFrom',date_to:'dateTo',duration:'durationFilter',missing:'missingFilter',sort:'sortFilter'};
const EXTRA_FILTERS = ['studio','actress','source','has_magnet','duration','missing','date_from','date_to'];
const shortDate = value => value ? value.slice(0,10) : '尚无记录';

export function createLibraryTools(env) {
  const {state,request,escapeHtml:esc,showToast,loadMovies,loadFilters} = env;
  const selected = new Set();
  let selecting = false;
  let listKey = '';
  let queueTimer;
  let detailBusy = false;

  async function action(button, work) {
    button.disabled = true;
    try { await work(); }
    catch (error) { showToast(error.message); }
    finally { button.disabled = false; }
  }

  function makeButton(label, work, className = 'text-button') {
    const button = document.createElement('button');
    button.type = 'button'; button.className = className; button.textContent = label;
    button.addEventListener('click', () => action(button, work));
    return button;
  }

  function remember() {
    localStorage.setItem('yav-browse', JSON.stringify({filters:state.filters,quick:state.quick,page:state.page,pageSize:state.pageSize,scroll:window.scrollY}));
  }

  function syncControls() {
    for (const [key,id] of Object.entries(FILTERS)) {
      const value = state.filters[key] || '';
      $('#'+id).value = key === 'actress' && value === state.filterData.unknown_value ? '未知演员' : value;
    }
    $('#pageSize').value = state.pageSize;
    $$('[data-quick]').forEach(button => {
      const active = button.dataset.quick === state.quick;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current','page');
      else button.removeAttribute('aria-current');
    });
  }

  function restore() {
    const saved = JSON.parse(localStorage.getItem('yav-browse'));
    if (!saved) return 0;
    Object.assign(state, {filters:saved.filters,quick:saved.quick,page:saved.page,pageSize:saved.pageSize});
    syncControls();
    return saved.scroll;
  }

  function toggleFilters(open) {
    $('#filterFields').hidden = !open;
    $('#toggleFilters').setAttribute('aria-expanded', String(open));
  }

  function init() {
    $('#toggleFilters').addEventListener('click', () => toggleFilters($('#filterFields').hidden));
    $('#closeFilters').addEventListener('click', () => toggleFilters(false));
    const inputs = {date_from:'dateFrom',date_to:'dateTo',duration:'durationFilter',missing:'missingFilter',sort:'sortFilter'};
    for (const [key,id] of Object.entries(inputs)) $('#'+id).addEventListener('change', () => {
      state.filters[key] = $('#'+id).value; state.page = 1; loadMovies();
    });
    $('#releaseYear').addEventListener('change', () => {
      const year = $('#releaseYear').value;
      state.filters.date_from = year ? year+'-01-01' : '';
      state.filters.date_to = year ? year+'-12-31' : '';
      state.page = 1; syncControls(); loadMovies();
    });
    $('#toggleSelection').addEventListener('click', () => setSelecting(!selecting));
    $('#finishSelection').addEventListener('click', () => setSelecting(false));
    $('#selectPage').addEventListener('click', () => {state.result.items.forEach(movie => selected.add(movie.id)); renderSelection();});
    $('#clearSelection').addEventListener('click', () => {selected.clear(); renderSelection();});
    for (const [id,favorite] of [['batchFavorite',true],['batchUnfavorite',false]]) $('#'+id).addEventListener('click', () => action($('#'+id), async () => {
      await request('/api/library/favorites', {method:'POST',body:JSON.stringify({ids:[...selected],favorite})});
      setSelecting(false); await loadFilters(); await loadMovies({silent:true}); showToast(favorite ? '已加入收藏' : '已取消收藏');
    }));
    for (const [id,format] of [['exportCsv','csv'],['exportTxt','txt']]) $('#'+id).addEventListener('click', () => {
      const params = new URLSearchParams(env.buildQuery()); params.set('format',format);
      if (selected.size) params.set('ids',[...selected].join(','));
      const link = document.createElement('a'); link.href = '/api/library/export?'+params; link.download = 'yav-library.'+format; link.click();
      $('#exportMenu').open = false;
    });
    $('#openLibraryTools').addEventListener('click', () => action($('#openLibraryTools'), openTools));
    $('#closeLibraryTools').addEventListener('click', () => $('#libraryToolsDialog').close());
    $('#libraryToolsDialog').addEventListener('close', () => {clearTimeout(queueTimer); $('#openLibraryTools').focus();});
    $('#editSourceSettings').addEventListener('click', () => {$('#libraryToolsDialog').close(); env.openSources();});
    $$('.tools-tabs [data-panel]').forEach(button => button.addEventListener('click', () => action(button, () => showPanel(button.dataset.panel))));
    $('.tools-tabs').addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight'].includes(event.key)) return;
      event.preventDefault(); const tabs = $$('.tools-tabs button');
      const index = tabs.indexOf(document.activeElement);
      const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length-1)) % tabs.length]; next.focus(); next.click();
    });
    $('#selectJavdb').addEventListener('click', () => $$('[data-queue-source]').forEach(input => input.checked = input.dataset.source === 'javdb'));
    $('#clearQueueSources').addEventListener('click', () => $$('[data-queue-source]').forEach(input => input.checked = false));
    for (const [id,operation,mode] of [['startQueue','start','scan'],['retryQueue','start','retry'],['resumeQueue','resume','scan'],['stopQueue','stop','scan']]) $('#'+id).addEventListener('click', () => action($('#'+id), async () => {
      const ids = $$('[data-queue-source]:checked').map(input => Number(input.value));
      await request('/api/library/queue/'+operation, {method:'POST',body:JSON.stringify({ids,mode})}); await refreshQueue();
    }));
    $('#makeBackup').addEventListener('click', () => action($('#makeBackup'), async () => {
      await request('/api/library/backup',{method:'POST',body:'{}'}); await renderBackup(); showToast('备份已保存');
    }));
    $('#openBackupFolder').addEventListener('click', () => action($('#openBackupFolder'), () => request('/api/library/open-backups',{method:'POST',body:'{}'})));
    let scrollTimer;
    window.addEventListener('scroll', () => {clearTimeout(scrollTimer); scrollTimer = setTimeout(remember,300);}, {passive:true});
  }

  function setSelecting(value) {
    selecting = value; selected.clear(); renderSelection();
  }

  function renderSelection() {
    document.body.classList.toggle('is-selecting',selecting);
    $('#selectionBar').hidden = !selecting;
    $('#toggleSelection').textContent = selecting ? '取消选择' : '选择';
    $('#selectedCount').textContent = selected.size ? `已选 ${selected.size} 部` : '选择想整理的影片';
    $('#batchFavorite').disabled = $('#batchUnfavorite').disabled = selected.size === 0;
    $('#exportHint').textContent = selected.size ? `已选的 ${selected.size} 部影片` : '当前筛选结果';
    $$('.movie-card').forEach(card => {
      const id = Number(card.dataset.id);
      card.classList.toggle('is-selected', selected.has(id));
      const existing=card.querySelector('.movie-selection');
      if (!selecting) {if (existing) existing.remove(); return;}
      if (existing) {existing.querySelector('input').checked=selected.has(id); return;}
      const label = document.createElement('label'); label.className = 'movie-selection';
      const input = document.createElement('input'); input.type='checkbox'; input.value=id; input.checked=selected.has(id); input.dataset.selectMovie='';
      input.setAttribute('aria-label','选择影片 '+card.querySelector('.card-title').textContent);
      input.addEventListener('change', () => {if (input.checked) selected.add(id); else selected.delete(id); renderSelection();});
      label.append(input); card.append(label);
    });
  }

  function renderFilterChips() {
    const names={studio:'厂商',actress:'演员',source:'来源',has_magnet:'磁链',duration:'时长',missing:'资料',date_from:'从',date_to:'至'};
    const from=state.filters.date_from || '', to=state.filters.date_to || '';
    const year=from.endsWith('-01-01') && to===from.slice(0,4)+'-12-31' ? from.slice(0,4) : '';
    const active=EXTRA_FILTERS.filter(key => state.filters[key] && !(year && ['date_from','date_to'].includes(key)));
    const count=active.length+(year ? 1 : 0);
    $('#filterCount').textContent = count ? String(count) : '';
    const chips = $('#activeFilters'); chips.replaceChildren();
    if (year) chips.append(makeButton(`年份：${year} ×`,()=>{delete state.filters.date_from; delete state.filters.date_to; state.page=1; syncControls(); return loadMovies();},'filter-chip'));
    for (const key of active) {
      const control = $('#'+FILTERS[key]);
      const value = control.tagName === 'SELECT' ? control.selectedOptions[0].textContent : control.value;
      chips.append(makeButton(`${names[key]}：${value} ×`, () => {
        delete state.filters[key]; state.page=1; syncControls(); return loadMovies();
      }, 'filter-chip'));
    }
    if (count) chips.append(makeButton('清除全部', () => env.clearFilters()));
  }

  function afterRender() {
    const key = env.buildQuery();
    if (listKey !== key) {selected.clear(); listKey=key;}
    renderSelection(); renderFilterChips(); remember();
    for (const [name,id] of Object.entries(FILTERS)) $('#'+id).value = name==='actress' && state.filters[name]===state.filterData.unknown_value ? '未知演员' : state.filters[name] || '';
    $('#releaseYear').innerHTML = '<option value="">全部年份</option>'+state.filterData.years.map(year => `<option value="${year}">${year} 年</option>`).join('');
    const from=state.filters.date_from || '', to=state.filters.date_to || '';
    $('#releaseYear').value = from.endsWith('-01-01') && to===from.slice(0,4)+'-12-31' ? from.slice(0,4) : '';
    const scope = $('#updateScope'); scope.hidden = !state.filters.run_id;
    if (state.filters.run_id) {
      const title={movies:'这次收录的新影片',old_magnets:'补到了新磁链的旧影片',magnets:'这次新增磁链的影片'}[state.filters.update_kind];
      scope.replaceChildren(document.createTextNode(title), makeButton('返回片库', () => {
        delete state.filters.run_id; delete state.filters.update_kind; state.page=1; return loadMovies();
      }));
    }
  }

  async function navigate(direction) {
    if (detailBusy) return;
    detailBusy=true;
    try {
      const index=state.result.items.findIndex(movie => movie.id===state.currentMovie.id);
      let next=index+direction;
      if (next<0 || next>=state.result.items.length) {
        const page=state.page+direction;
        if (page<1 || page>state.result.pages) return;
        state.page=page; await loadMovies({silent:true}); next=direction>0 ? 0 : state.result.items.length-1;
      }
      await env.openDetail(state.result.items[next].id);
    } finally {detailBusy=false;}
  }

  async function replaceDetail(movie) {
    state.currentMovie=movie; env.renderDetail(movie); await loadMovies({silent:true});
  }

  function afterDetail(movie) {
    const navigation=document.createElement('div'); navigation.className='detail-navigation';
    const previous=makeButton('← 上一部',()=>navigate(-1)); const next=makeButton('下一部 →',()=>navigate(1));
    const index=state.result.items.findIndex(item => item.id===movie.id);
    previous.disabled=index<=0 && state.page===1; next.disabled=index===state.result.items.length-1 && state.page===state.result.pages;
    navigation.append(previous,next); navigation.hidden=state.result.total<=1; $('.detail-actions').after(navigation);
    const keys={'厂商':'studio','系列':'series','演员':'actress'};
    $$('.detail-fact').forEach(fact => {
      const key=keys[fact.querySelector('span').textContent]; if (!key) return;
      const values=key==='actress' ? movie.actresses : movie[key] ? [movie[key]] : [];
      if (!values.length) return;
      const container=fact.querySelector('strong'); container.replaceChildren();
      for (const value of values) container.append(makeButton(value,async()=>{
        env.closeDetail(); state.filters[key]=value; state.quick='all'; state.page=1; syncControls(); await loadMovies({scroll:true});
      },'fact-link'));
    });
    $$('#editForm input').forEach(input => {
      if (!movie.manual_fields.includes(input.name)) return;
      const mark=document.createElement('small'); mark.className='manual-marker'; mark.textContent='你修改过'; input.parentElement.append(mark);
    });
    const coverMenu=$('#detailCoverMenu');
    coverMenu.append(makeButton('重新获取封面',async()=>replaceDetail(await request(`/api/movies/${movie.id}/cover`,{method:'POST',body:JSON.stringify({action:'refresh'})}))));
    const file=document.createElement('input'); file.type='file'; file.accept='image/png,image/jpeg,image/webp,image/gif'; file.hidden=true;
    const upload=makeButton('更换本地封面',()=>file.click());
    file.addEventListener('change',()=>{
      if (!file.files.length) return;
      action(upload,async()=>{
        const image=file.files[0];
        if (image.size>8*1024*1024) throw new Error('封面请选择 8 MB 以内的图片');
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader(); reader.onload=()=>resolve(reader.result.split(',')[1]); reader.onerror=()=>reject(new Error('图片没有读成功，请重试')); reader.readAsDataURL(image);});
        await replaceDetail(await request(`/api/movies/${movie.id}/cover`,{method:'POST',body:JSON.stringify({data})})); showToast('封面已更换');
      });
    });
    coverMenu.append(upload,file);
    renderMagnets(movie);
    renderSourceComparison(movie);
  }

  function renderMagnets(movie) {
    const heading=$('.magnet-heading');
    const select=document.createElement('select'); select.setAttribute('aria-label','磁链排序');
    select.innerHTML='<option value="size">按大小</option><option value="newest">最近收录</option>'; heading.append(select);
    function render() {
      const magnets=[...movie.magnets];
      if (select.value==='newest') magnets.sort((a,b)=>b.discovered_at.localeCompare(a.discovered_at)||b.id-a.id);
      const previous=$('.magnet-list') || $('.no-magnets'); previous.remove();
      const template=document.createElement('template'); template.innerHTML=env.magnetList(magnets);
      heading.parentElement.insertBefore(template.content,$('#editForm'));
      $$('.magnet-row').forEach((row,index)=>{
        const date=document.createElement('small'); date.className='magnet-discovery'; date.textContent=shortDate(magnets[index].discovered_at)+' 收录'; row.append(date);
      });
      heading.querySelector('p').textContent=movie.magnets.length ? `${movie.magnets.length} 条可用磁链` : '尚未收录磁链';
    }
    select.addEventListener('change',render); render();
  }

  function renderSourceComparison(movie) {
    const compare=document.createElement('details'); compare.className='source-compare'; compare.id='sourceCompare';
    compare.innerHTML='<summary>参考来源资料</summary><p>选择采用后，会作为你的修改保存。</p>';
    const fields={title:'影片名',studio:'厂商',series:'系列',release_date:'日期',duration_minutes:'时长',cover_url:'封面'};
    for (const source of movie.sources) {
      const section=document.createElement('section'); const title=document.createElement('h4'); title.textContent=source.source.toUpperCase(); section.append(title);
      for (const [key,label] of Object.entries(fields)) {
        const value=key==='title' ? source.source_title : source[key];
        if (value===null || value===undefined || value==='') continue;
        const row=document.createElement('div'); row.className='compare-row'; const text=document.createElement('span'); text.textContent=`${label}：${value}`; row.append(text);
        if (String(value)!==String(movie[key] ?? '')) row.append(makeButton('采用',async()=>{
          await replaceDetail(await request(`/api/movies/${movie.id}`,{method:'PATCH',body:JSON.stringify({[key]:value})}));
          $('#editForm').hidden=false; $('#sourceCompare').open=true; await loadFilters();
        }));
        section.append(row);
      }
      compare.append(section);
    }
    $('#editForm').append(compare);
  }

  async function openTools() {
    $('#libraryToolsDialog').showModal(); $('#closeLibraryTools').focus();
    const sources=(await Promise.all(['javdb','jphoo','avfan'].map(source=>request('/api/sources/'+source)))).flat();
    $('#queueSources').innerHTML=sources.filter(source=>source.enabled).map(source=>`<label class="series-choice"><input type="checkbox" data-queue-source data-source="${esc(source.source)}" value="${source.id}"><span>${esc(source.name)}</span><small>${source.source.toUpperCase()}</small></label>`).join('');
    await showPanel('updates');
  }

  async function showPanel(name) {
    $$('.tools-tabs button').forEach(button=>button.setAttribute('aria-selected',String(button.dataset.panel===name)));
    $$('#libraryToolsDialog [role=tabpanel]').forEach(panel=>panel.hidden=panel.id!=='panel-'+name);
    const render={updates:refreshQueue,results:renderResults,failures:renderFailures,backups:renderBackup};
    await render[name]();
  }

  async function refreshQueue() {
    clearTimeout(queueTimer);
    const queue=await request('/api/library/queue');
    $('#startQueue').disabled=$('#retryQueue').disabled=queue.running;
    $('#stopQueue').hidden=!queue.running;
    $('#resumeQueue').hidden=queue.running || !['stopped','interrupted','needs_attention'].includes(queue.status);
    const progress=$('#queueProgress'); progress.replaceChildren();
    if (!queue.id) return;
    const title=document.createElement('h4'); title.textContent=STATUS[queue.status]; progress.append(title);
    const completed=queue.items.filter(item=>item.status==='completed').length;
    const movies=queue.items.reduce((n,item)=>n+(item.new_movies||0),0), magnets=queue.items.reduce((n,item)=>n+(item.new_magnets||0),0);
    const summary=document.createElement('p'); summary.textContent=`已完成 ${completed} / ${queue.items.length} 个系列 · 新收录 ${movies} 部 · 新磁链 ${magnets} 条`; progress.append(summary);
    for (const item of queue.items) {
      const row=document.createElement('div'); row.className='queue-item';
      const name=document.createElement('span'); name.textContent=item.name;
      const status=document.createElement('span'); status.textContent=item.status==='running' ? `第 ${item.current_page||1} 页 · 已整理 ${item.processed_count||0} 部` : STATUS[item.status];
      row.append(name,status); progress.append(row);
    }
    if (queue.last_error) {
      const reason=document.createElement('details'); reason.className='technical-details'; const heading=document.createElement('summary'); heading.textContent='查看暂停原因';
      const text=document.createElement('p'); text.textContent=queue.last_error; reason.append(heading,text); progress.append(reason);
    }
    if (queue.running && $('#libraryToolsDialog').open) queueTimer=setTimeout(()=>refreshQueue().catch(error=>showToast(error.message)),1500);
    else if (queue.status==='completed') {await loadFilters(); await loadMovies({silent:true});}
  }

  async function showResult(run,kind) {
    state.filters={run_id:String(run.id),update_kind:kind}; state.quick='all'; state.page=1;
    syncControls(); $('#libraryToolsDialog').close(); await loadMovies({scroll:true});
  }

  async function renderResults() {
    const scans=await request('/api/library/scans'); const container=$('#scanHistory'); container.replaceChildren();
    for (const scan of scans.filter(scan=>scan.status!=='idle')) {
      const row=document.createElement('article'); row.className='scan-result';
      const head=document.createElement('div'); head.className='result-title'; const title=document.createElement('h4'); title.textContent=scan.name;
      const date=document.createElement('small'); date.textContent=shortDate(scan.started_at)+' · '+STATUS[scan.status]; head.append(title,date); row.append(head);
      const counts=document.createElement('p'); counts.textContent=`新收录 ${scan.new_movies} 部影片，补充 ${scan.new_magnets} 条磁链`; row.append(counts);
      if (scan.tracked_count) {
        const links=document.createElement('div'); links.className='result-links';
        links.append(makeButton('查看新影片',()=>showResult(scan,'movies')),makeButton('查看新增磁链',()=>showResult(scan,'magnets')));
        const more=document.createElement('details'); more.className='result-more'; more.innerHTML='<summary>更多</summary>'; more.append(makeButton('仅看旧影片的新磁链',()=>showResult(scan,'old_magnets'))); links.append(more); row.append(links);
      }
      container.append(row);
    }
    if (!container.children.length) container.textContent='更新后，新收录的影片会出现在这里。';
  }

  async function renderFailures() {
    const failures=await request('/api/library/failures'); const groups=new Map();
    for (const failure of failures) {
      const key=failure.series_id+':'+failure.kind;
      if (!groups.has(key)) groups.set(key,[]);
      groups.get(key).push(failure);
    }
    const container=$('#scanFailures'); container.replaceChildren();
    for (const rows of groups.values()) {
      const first=rows[0], row=document.createElement('article'); row.className='failure-row';
      const title=document.createElement('h4'); title.textContent=first.name;
      const reason=document.createElement('p'); reason.textContent=`${rows.length} 个页面 · ${first.kind}`; row.append(title,reason);
      const details=document.createElement('details'); details.className='technical-details'; details.innerHTML='<summary>查看页面</summary>';
      for (const failure of rows) {const link=document.createElement('a'); link.href=failure.source_url; link.target='_blank'; link.rel='noopener noreferrer'; link.textContent=failure.source_url; details.append(link);}
      const retry=makeButton('重新尝试',async()=>{await request('/api/library/queue/start',{method:'POST',body:JSON.stringify({ids:[first.series_id],mode:'retry'})}); await showPanel('updates');});
      if (first.kind.includes('版权')) details.append(retry); else row.append(retry);
      row.append(details); container.append(row);
    }
    if (!groups.size) container.innerHTML='<p class="panel-empty">没有需要处理的页面。</p>';
  }

  async function renderBackup() {
    const backup=await request('/api/library/backups');
    $('#backupSummary').textContent=backup.created_at ? '最近一次备份：'+shortDate(backup.created_at) : '还没有备份，给现在的片库留一份副本吧。';
    $('#backupPath').textContent=backup.latest || backup.directory;
  }

  return {init,restore,afterRender,afterDetail,remember};
}

const state = {
  page: 1,
  pageSize: 36,
  view: localStorage.getItem('yav-view') || 'gallery',
  quick: 'all',
  filters: { q: '', studio: '', series: '', actress: '', source: '', has_magnet: '' },
  result: { items: [], total: 0, pages: 1 },
  filterData: null,
  currentMovie: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
}

function formatSize(bytes) {
  const value = Number(bytes || 0);
  if (!value) return '大小未知';
  const gb = value / (1024 ** 3);
  if (gb >= 1) return `${gb.toFixed(gb >= 10 ? 1 : 2)} GB`;
  const mb = value / (1024 ** 2);
  return `${mb.toFixed(mb >= 10 ? 0 : 1)} MB`;
}

function displayDate(value) {
  if (!value) return '';
  return String(value).slice(0, 10);
}

function posterMarkup(movie, className = '') {
  if (movie.cover_src) {
    return `<img class="${className}" src="${escapeHtml(movie.cover_src)}" alt="${escapeHtml(movie.title)}" loading="lazy" data-fallback-letter="${escapeHtml((movie.title || 'Y').slice(0, 1))}">`;
  }
  return `<div class="poster-fallback ${className}"><span>${escapeHtml((movie.title || 'Y').slice(0, 1))}</span></div>`;
}

window.posterFallback = (letter, extraClass = '') => {
  const node = document.createElement('div');
  node.className = `poster-fallback ${extraClass}`.trim();
  node.innerHTML = `<span>${letter || 'Y'}</span>`;
  return node;
};

function sourcePills(counts = {}) {
  const entries = Object.entries(counts);
  if (!entries.length) return '<span class="source-pill"><span>暂无磁链</span></span>';
  return entries.map(([source, count]) =>
    `<span class="source-pill"><span>${escapeHtml(source)}</span><b>${count}</b></span>`
  ).join('');
}

function movieCard(movie) {
  const meta = [movie.studio, displayDate(movie.release_date)].filter(Boolean);
  return `
    <article class="movie-card" data-id="${movie.id}">
      <button class="favorite-card-btn ${movie.favorite ? 'is-active' : ''}" data-favorite="${movie.id}" aria-label="${movie.favorite ? '取消收藏' : '添加收藏'}">${movie.favorite ? '♥' : '♡'}</button>
      <button class="poster-button" data-open="${movie.id}">
        <div class="poster-frame">
          ${posterMarkup(movie)}
          <div class="source-pills">${sourcePills(movie.source_counts)}</div>
        </div>
        <div class="card-copy">
          <h4 class="card-title">${escapeHtml(movie.title)}</h4>
          <div class="card-meta">${meta.length ? meta.map(item => `<span>${escapeHtml(item)}</span>`).join('') : '<span>资料待补全</span>'}</div>
          <div class="card-actresses">${movie.actresses?.length ? escapeHtml(movie.actresses.join(' · ')) : '未知女演员'}</div>
        </div>
      </button>
    </article>`;
}

async function request(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function buildQuery() {
  const params = new URLSearchParams();
  Object.entries(state.filters).forEach(([key, value]) => {
    if (value !== '' && value != null) params.set(key, value);
  });
  if (state.quick === 'favorite') params.set('favorite', 'true');
  if (state.quick === 'with-magnets') params.set('has_magnet', 'true');
  if (state.quick === 'without-magnets') params.set('has_magnet', 'false');
  params.set('page', state.page);
  params.set('page_size', state.pageSize);
  return params.toString();
}

async function loadFilters() {
  state.filterData = await request('/api/filters');
  const { stats } = state.filterData;
  $('#navTotal').textContent = stats.total.toLocaleString('zh-CN');
  $('#navFavorites').textContent = stats.favorites.toLocaleString('zh-CN');
  $('#navWithMagnets').textContent = stats.with_magnets.toLocaleString('zh-CN');
  $('#navWithoutMagnets').textContent = Math.max(0, stats.total - stats.with_magnets).toLocaleString('zh-CN');
  $('#statMovies').textContent = stats.total.toLocaleString('zh-CN');
  $('#statMagnets').textContent = stats.magnets.toLocaleString('zh-CN');
  $('#statFavorites').textContent = stats.favorites.toLocaleString('zh-CN');

  fillSelect('#studioFilter', state.filterData.studios, '全部厂商', '未知厂商');
  fillSelect('#seriesFilter', state.filterData.series, '全部系列', '未分类系列');
  fillSelect('#actressFilter', state.filterData.actresses, '全部女演员', '未知女演员');
  fillSelect('#sourceFilter', state.filterData.sources, '全部来源');
}

function fillSelect(selector, values, allLabel, unknownLabel = '') {
  const select = $(selector);
  const current = select.value;
  const unknown = unknownLabel ? `<option value="${state.filterData.unknown_value}">${unknownLabel}</option>` : '';
  select.innerHTML = `<option value="">${allLabel}</option>${unknown}${values.map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('')}`;
  select.value = current;
}

function showSkeletons() {
  $('#emptyState').hidden = true;
  $('#movieGrid').innerHTML = Array.from({ length: Math.min(12, state.pageSize) }, () => '<div class="loading-card"></div>').join('');
}

async function loadMovies({ scroll = false } = {}) {
  showSkeletons();
  try {
    state.result = await request(`/api/movies?${buildQuery()}`);
    renderMovies();
    if (scroll) $('.content-head').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    $('#movieGrid').innerHTML = '';
    $('#emptyState').hidden = false;
    $('#emptyState h3').textContent = '读取资料库失败';
    $('#emptyState p').textContent = error.message;
  }
}

function renderMovies() {
  const { items, total, page, pages } = state.result;
  const grid = $('#movieGrid');
  grid.className = `movie-grid view-${state.view}`;
  grid.innerHTML = items.map(movieCard).join('');
  $('#emptyState').hidden = items.length > 0;
  $('#pagination').hidden = total === 0;
  $('#resultSummary').textContent = `当前筛选找到 ${total.toLocaleString('zh-CN')} 部影片`;
  $('#contentTitle').textContent = currentTitle();
  $('#prevPage').disabled = page <= 1;
  $('#nextPage').disabled = page >= pages;
  renderPageNumbers(page, pages);
}

function currentTitle() {
  if (state.quick === 'favorite') return '我的收藏';
  if (state.quick === 'with-magnets') return '已有磁链';
  if (state.quick === 'without-magnets') return '等待补全';
  const selected = [
    $('#studioFilter').selectedOptions[0]?.textContent,
    $('#seriesFilter').selectedOptions[0]?.textContent,
    $('#actressFilter').selectedOptions[0]?.textContent,
  ].filter(text => text && !text.startsWith('全部'));
  return selected.length ? selected.join(' · ') : '全部影片';
}

function renderPageNumbers(page, pages) {
  const wrap = $('#pageNumbers');
  const numbers = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2]);
  const valid = [...numbers].filter(n => n >= 1 && n <= pages).sort((a, b) => a - b);
  let previous = 0;
  wrap.innerHTML = valid.map(number => {
    const gap = previous && number - previous > 1 ? '<span>…</span>' : '';
    previous = number;
    return `${gap}<button class="${number === page ? 'is-active' : ''}" data-page="${number}">${number}</button>`;
  }).join('');
}

async function toggleFavorite(id, nextValue, button) {
  button.disabled = true;
  try {
    const result = await request(`/api/movies/${id}/favorite`, {
      method: 'POST', body: JSON.stringify({ favorite: nextValue }),
    });
    button.classList.toggle('is-active', result.favorite);
    button.textContent = result.favorite ? '♥' : '♡';
    const movie = state.result.items.find(item => item.id === Number(id));
    if (movie) movie.favorite = result.favorite;
    if (state.currentMovie?.id === Number(id)) state.currentMovie.favorite = result.favorite;
    const delta = result.favorite ? 1 : -1;
    const current = Number($('#statFavorites').textContent.replaceAll(',', '')) || 0;
    $('#statFavorites').textContent = Math.max(0, current + delta).toLocaleString('zh-CN');
    $('#navFavorites').textContent = $('#statFavorites').textContent;
    if (state.quick === 'favorite' && !result.favorite) loadMovies();
    showToast(result.favorite ? '已加入收藏' : '已取消收藏');
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function openDetail(id) {
  $('#detailOverlay').hidden = false;
  document.body.style.overflow = 'hidden';
  $('#detailContent').innerHTML = '<div style="padding:100px;text-align:center">正在读取影片资料…</div>';
  try {
    state.currentMovie = await request(`/api/movies/${id}`);
    renderDetail(state.currentMovie);
  } catch (error) {
    $('#detailContent').innerHTML = `<div style="padding:100px;text-align:center">${escapeHtml(error.message)}</div>`;
  }
}

function renderDetail(movie) {
  const facts = [
    ['厂商', movie.studio || '未知厂商'],
    ['系列', movie.series || '未分类系列'],
    ['日期', displayDate(movie.release_date) || '未知日期'],
    ['时长', movie.duration_minutes ? `${movie.duration_minutes} 分钟` : '未知时长'],
    ['女演员', movie.actresses?.join('、') || '未知女演员'],
    ['来源页面', `${movie.sources?.length || 0} 个`],
  ];
  $('#detailContent').innerHTML = `
    <section class="detail-hero">
      <div>${posterMarkup(movie, 'detail-poster')}</div>
      <div class="detail-copy">
        <div class="detail-kicker">PRIVATE LIBRARY ENTRY · #${movie.id}</div>
        <h2 id="detailTitle">${escapeHtml(movie.title)}</h2>
        <div class="detail-facts">${facts.map(([label, value]) => `<div class="detail-fact"><span>${label}</span><strong>${escapeHtml(value)}</strong></div>`).join('')}</div>
        <div class="detail-actions">
          <button class="primary-action" id="editMovie">编辑资料</button>
          <button class="secondary-action ${movie.favorite ? 'is-active' : ''}" id="detailFavorite">${movie.favorite ? '♥ 已收藏' : '♡ 加入收藏'}</button>
        </div>
      </div>
    </section>
    <section class="detail-body">
      <div class="magnet-heading">
        <div><div class="content-kicker">MAGNET COLLECTION</div><h3>磁链收藏</h3></div>
        <p>共 ${movie.magnets.length} 条唯一 BTIH，按文件大小排序</p>
      </div>
      ${magnetList(movie.magnets)}
      ${editForm(movie)}
    </section>`;
}

function magnetList(magnets) {
  if (!magnets.length) return '<div class="no-magnets">当前影片暂无磁链，等待其他来源补全。</div>';
  return `<div class="magnet-list">${magnets.map(magnet => {
    const sources = magnet.sources?.length ? magnet.sources : [{ source: '未知来源', source_url: '' }];
    const sourceTags = sources.map(item => `<span class="magnet-source">${escapeHtml(item.source)}</span>`).join('');
    const openLinks = sources.filter(item => item.source_url).map(item => `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">打开 ${escapeHtml(item.source)}</a>`).join('');
    return `<article class="magnet-row">
      <div class="magnet-sources">${sourceTags}</div>
      <div class="magnet-size">${formatSize(magnet.size_bytes)}</div>
      <div class="magnet-hash" title="${escapeHtml(magnet.btih)}">BTIH · ${escapeHtml(magnet.btih.slice(0, 12))}…${escapeHtml(magnet.btih.slice(-8))}</div>
      <div class="magnet-actions">
        ${openLinks}
        <button class="copy-magnet" data-copy="${escapeHtml(magnet.magnet)}">复制磁链</button>
      </div>
    </article>`;
  }).join('')}</div>`;
}

function editForm(movie) {
  return `<form id="editForm" class="edit-form" hidden>
    <label class="wide">影片名<input name="title" value="${escapeHtml(movie.title)}" required></label>
    <label>封面网址<input name="cover_url" value="${escapeHtml(movie.cover_url || '')}" placeholder="https://..."></label>
    <label>厂商<input name="studio" value="${escapeHtml(movie.studio || '')}"></label>
    <label>系列<input name="series" value="${escapeHtml(movie.series || '')}"></label>
    <label>日期<input name="release_date" value="${escapeHtml(movie.release_date || '')}" placeholder="YYYY-MM-DD"></label>
    <label>时长（分钟）<input name="duration_minutes" type="number" min="0" value="${movie.duration_minutes ?? ''}"></label>
    <label class="wide">女演员<input name="actresses" value="${escapeHtml((movie.actresses || []).join('、'))}" placeholder="多人请用顿号或逗号分隔"></label>
    <div class="save-row"><button type="submit">保存手动修改</button></div>
  </form>`;
}

async function saveEdit(form) {
  const payload = Object.fromEntries(new FormData(form).entries());
  payload.duration_minutes = payload.duration_minutes === '' ? null : Number(payload.duration_minutes);
  payload.actresses = payload.actresses.split(/[,，、\n]+/).map(v => v.trim()).filter(Boolean);
  try {
    const movie = await request(`/api/movies/${state.currentMovie.id}`, {
      method: 'PATCH', body: JSON.stringify(payload),
    });
    state.currentMovie = movie;
    renderDetail(movie);
    await Promise.all([loadFilters(), loadMovies()]);
    showToast('影片资料已保存');
  } catch (error) {
    showToast(error.message);
  }
}

function closeDetail() {
  $('#detailOverlay').hidden = true;
  document.body.style.overflow = '';
  state.currentMovie = null;
}

function clearFilters() {
  state.quick = 'all';
  state.page = 1;
  state.filters = { q: '', studio: '', series: '', actress: '', source: '', has_magnet: '' };
  $('#searchInput').value = '';
  $('#studioFilter').value = '';
  $('#seriesFilter').value = '';
  $('#actressFilter').value = '';
  $('#sourceFilter').value = '';
  $('#magnetFilter').value = '';
  $$('.nav-item').forEach(item => item.classList.toggle('is-active', item.dataset.quick === 'all'));
  loadMovies({ scroll: true });
}

let toastTimer;
function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('is-visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove('is-visible'), 2200);
}

function bindEvents() {
  document.addEventListener('error', event => {
    const image = event.target;
    if (image instanceof HTMLImageElement && image.dataset.fallbackLetter) {
      image.replaceWith(window.posterFallback(image.dataset.fallbackLetter, image.className));
    }
  }, true);

  $('#searchInput').addEventListener('keydown', event => {
    if (event.key === 'Enter') {
      state.filters.q = event.target.value.trim(); state.page = 1; loadMovies();
    }
  });
  $('#searchInput').addEventListener('search', event => {
    state.filters.q = event.target.value.trim(); state.page = 1; loadMovies();
  });

  const filterBindings = {
    studioFilter: 'studio', seriesFilter: 'series', actressFilter: 'actress',
    sourceFilter: 'source', magnetFilter: 'has_magnet',
  };
  Object.entries(filterBindings).forEach(([id, key]) => {
    $(`#${id}`).addEventListener('change', event => {
      state.filters[key] = event.target.value; state.page = 1; loadMovies();
    });
  });

  $('#pageSize').addEventListener('change', event => {
    state.pageSize = Number(event.target.value); state.page = 1; loadMovies();
  });
  $('#clearFilters').addEventListener('click', clearFilters);
  $('#emptyClear').addEventListener('click', clearFilters);

  $$('.nav-item').forEach(button => button.addEventListener('click', () => {
    state.quick = button.dataset.quick; state.page = 1;
    $$('.nav-item').forEach(item => item.classList.toggle('is-active', item === button));
    loadMovies({ scroll: true });
  }));

  $$('.category-link').forEach(button => button.addEventListener('click', () => {
    $(`#${button.dataset.focus}Filter`).focus();
    $('.filter-panel').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));

  $$('.view-btn').forEach(button => {
    button.classList.toggle('is-active', button.dataset.view === state.view);
    button.addEventListener('click', () => {
      state.view = button.dataset.view;
      localStorage.setItem('yav-view', state.view);
      $$('.view-btn').forEach(item => item.classList.toggle('is-active', item === button));
      renderMovies();
    });
  });

  $('#movieGrid').addEventListener('click', event => {
    const favorite = event.target.closest('[data-favorite]');
    if (favorite) {
      const movie = state.result.items.find(item => item.id === Number(favorite.dataset.favorite));
      toggleFavorite(favorite.dataset.favorite, !movie?.favorite, favorite);
      return;
    }
    const open = event.target.closest('[data-open]');
    if (open) openDetail(open.dataset.open);
  });

  $('#prevPage').addEventListener('click', () => { if (state.page > 1) { state.page--; loadMovies({ scroll: true }); } });
  $('#nextPage').addEventListener('click', () => { if (state.page < state.result.pages) { state.page++; loadMovies({ scroll: true }); } });
  $('#pageNumbers').addEventListener('click', event => {
    const button = event.target.closest('[data-page]');
    if (button) { state.page = Number(button.dataset.page); loadMovies({ scroll: true }); }
  });

  $('#closeDetail').addEventListener('click', closeDetail);
  $('#detailOverlay').addEventListener('click', event => { if (event.target === $('#detailOverlay')) closeDetail(); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && !$('#detailOverlay').hidden) closeDetail(); });

  $('#detailContent').addEventListener('click', event => {
    const copy = event.target.closest('[data-copy]');
    if (copy) {
      navigator.clipboard.writeText(copy.dataset.copy).then(() => showToast('磁链已复制')).catch(() => showToast('复制失败，请检查浏览器权限'));
      return;
    }
    if (event.target.closest('#editMovie')) {
      $('#editForm').hidden = !$('#editForm').hidden;
      if (!$('#editForm').hidden) $('#editForm input').focus();
      return;
    }
    const favorite = event.target.closest('#detailFavorite');
    if (favorite && state.currentMovie) {
      toggleFavorite(state.currentMovie.id, !state.currentMovie.favorite, favorite).then(() => {
        favorite.textContent = state.currentMovie.favorite ? '♥ 已收藏' : '♡ 加入收藏';
      });
    }
  });
  $('#detailContent').addEventListener('submit', event => {
    if (event.target.id === 'editForm') { event.preventDefault(); saveEdit(event.target); }
  });
}

async function init() {
  bindEvents();
  try {
    await loadFilters();
    await loadMovies();
  } catch (error) {
    showToast(error.message);
  }
}

init();

async function renderSources(){const rows=await request('/api/sources/javdb');const status=await request('/api/sources/javdb/scan');$('#sourceContent').innerHTML=`<h2>JavDB 来源</h2><p>状态：${escapeHtml(status.status||'idle')}；当前页：${status.page||0}；新增影片：${status.new_movies||0}；新增磁链：${status.new_magnets||0}；失败：${status.failures||0}</p><form id="sourceForm" class="source-form"><input name="name" placeholder="系列名称" required><input name="url" placeholder="JavDB 系列网址" required><button>添加</button></form>${rows.map(x=>`<div class="source-row"><strong>${escapeHtml(x.name)}</strong><br><small>${escapeHtml(x.url)} · 完成页 ${x.last_completed_page||0}</small><br><button data-scan="${x.id}">全量扫描</button><button data-continue="${x.id}">继续扫描</button><button data-delete-source="${x.id}">删除</button></div>`).join('')||'<p>尚未配置 JavDB 系列。</p>'}`}
$('#openSources').addEventListener('click',async()=>{$('#sourceOverlay').hidden=false;await renderSources()});$('#closeSources').addEventListener('click',()=>$('#sourceOverlay').hidden=true);$('#sourceOverlay').addEventListener('click',e=>{if(e.target===$('#sourceOverlay'))$('#sourceOverlay').hidden=true});$('#sourceContent').addEventListener('submit',async e=>{if(e.target.id!=='sourceForm')return;e.preventDefault();const f=e.target;await request('/api/sources/javdb',{method:'POST',body:JSON.stringify({name:f.name.value,url:f.url.value,enabled:true})});await renderSources()});$('#sourceContent').addEventListener('click',async e=>{const b=e.target;if(b.dataset.scan)await request(`/api/sources/javdb/${b.dataset.scan}/scan`,{method:'POST',body:'{}'});if(b.dataset.continue)await request(`/api/sources/javdb/${b.dataset.continue}/continue`,{method:'POST',body:'{}'});if(b.dataset.deleteSource)await request(`/api/sources/javdb/${b.dataset.deleteSource}`,{method:'DELETE'});await renderSources()});

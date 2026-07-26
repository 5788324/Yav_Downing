const state = {
  page: 1,
  pageSize: 36,
  view: localStorage.getItem('yav-view') || 'gallery',
  quick: 'all',
  filters: { q: '', studio: '', series: '', actress: '', source: '', has_magnet: '' },
  result: { items: [], total: 0, pages: 1 },
  filterData: null,
  currentMovie: null,
  detailLastTrigger: null,
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
  fillSelect('#sourceFilter', state.filterData.sources, '全部磁链来源');
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
    button.setAttribute('aria-label', result.favorite ? '取消收藏' : '添加收藏');
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
  state.detailLastTrigger = document.activeElement;
  $('#detailOverlay').hidden = false;
  document.body.style.overflow = 'hidden';
  $('#closeDetail').focus();
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
    <label>封面网址<input name="cover_url" type="url" value="${escapeHtml(movie.cover_url || '')}" placeholder="https://..."></label>
    <label>厂商<input name="studio" value="${escapeHtml(movie.studio || '')}"></label>
    <label>系列<input name="series" value="${escapeHtml(movie.series || '')}"></label>
    <label>日期<input name="release_date" type="date" value="${escapeHtml(movie.release_date || '')}"></label>
    <label>时长（分钟）<input name="duration_minutes" type="number" min="0" max="1440" value="${movie.duration_minutes ?? ''}"></label>
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

function closeDetail() { $('#detailOverlay').hidden = true; document.body.style.overflow = ''; state.currentMovie = null; state.detailLastTrigger?.focus(); }

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
  $$('.nav-item[data-quick]').forEach(item => { const active=item.dataset.quick === 'all'; item.classList.toggle('is-active', active); active ? item.setAttribute('aria-current','page') : item.removeAttribute('aria-current'); });
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

  $$('.nav-item[data-quick]').forEach(button => button.addEventListener('click', () => {
    state.quick = button.dataset.quick; state.page = 1;
    $$('.nav-item[data-quick]').forEach(item => { const active=item === button; item.classList.toggle('is-active', active); active ? item.setAttribute('aria-current','page') : item.removeAttribute('aria-current'); });
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
      $$('.view-btn').forEach(item => { item.classList.toggle('is-active', item === button); item.setAttribute('aria-pressed', String(item === button)); });
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
document.addEventListener('keydown', event => { if (event.key !== 'Escape') return; if (!$('#sourceOverlay').hidden) closeSources(); else if (!$('#detailOverlay').hidden) closeDetail(); });

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

let sourcePollTimer = null;
let sourceOpBusy = false;
let sourceLastTrigger = null;

function sourcePayload(form, source) {
  return {
    series_id: form.dataset.editId ? Number(form.dataset.editId) : undefined,
    name: form.name.value.trim(), url: form.url.value.trim(), enabled: form.enabled.checked,
    profile_dir: source === 'jphoo' ? form.profile_dir.value.trim() : '',
  };
}
function sourceButtons(item) {
  const state = item.scan_status || (item.enabled ? 'idle' : 'disabled');
  const locked = ['running', 'stopping'].includes(state);
  const disabled = !item.enabled || locked;
  if (state === 'running') return `<button data-source="${item.source}" data-stop="${item.id}">停止扫描</button>`;
  if (state === 'stopping') return '<button disabled>正在停止…</button>';
  if (!item.enabled) return `<button data-source="${item.source}" data-toggle="${item.id}" data-enabled="true">启用</button><button data-source="${item.source}" data-edit="${item.id}">编辑</button><button data-source="${item.source}" data-delete="${item.id}">删除</button>`;
  if (state === 'login_required') return '<span class="source-hint">JPHOO 需要重新登录</span>';
  return `<button data-source="${item.source}" data-scan="${item.id}" ${disabled ? 'disabled' : ''}>全量扫描</button><button data-source="${item.source}" data-continue="${item.id}" ${disabled ? 'disabled' : ''}>继续扫描</button><button data-source="${item.source}" data-edit="${item.id}" ${locked ? 'disabled' : ''}>编辑</button><button data-source="${item.source}" data-toggle="${item.id}" data-enabled="false" ${locked ? 'disabled' : ''}>停用</button><button data-source="${item.source}" data-delete="${item.id}" ${locked ? 'disabled' : ''}>删除</button>`;
}
function sourceCard(item) {
  const stats = `页 ${item.current_page || item.last_completed_page || 0} · 发现 ${item.discovered || 0} · 处理 ${item.processed_count || 0} · 新磁链 ${item.new_magnets || 0} · 失败 ${item.failures || 0}`;
  return `<article class="source-card" data-source-card="${item.source}-${item.id}"><div><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.url)}</p><small>${item.enabled ? '已启用' : '已停用'} · ${stats}${item.last_error ? ` · ${escapeHtml(item.last_error)}` : ''}</small></div><div class="source-actions">${sourceButtons(item)}</div></article>`;
}
function sourceForm(source, label) {
  return `<form class="source-form" data-source-form="${source}"><h3 data-form-title>添加 ${label} 系列</h3><input name="name" placeholder="系列名称" required><input name="url" type="url" placeholder="${label} 系列网址" required>${source === 'jphoo' ? '<input name="profile_dir" placeholder="浏览器资料目录（留空使用默认）">' : ''}<label class="source-check"><input name="enabled" type="checkbox" checked> 启用此系列</label><div><button type="submit">保存系列</button><button type="button" data-cancel-edit hidden>取消编辑</button></div></form>`;
}
async function sourcePanel(source, label) {
  const [rows, scan, login] = await Promise.all([request(`/api/sources/${source}`), request(`/api/sources/${source}/scan`), source === 'jphoo' ? request('/api/sources/jphoo/login') : Promise.resolve({})]);
  const loginCard = source === 'jphoo' ? `<section class="source-status-card"><h3>JPHOO 登录状态：<span data-login-state>${escapeHtml(login.login || login.status || 'unknown')}</span></h3><p>仅使用 Yav V2 专用 Edge，不读取或提交 Cookie。</p><button data-login="open">打开登录窗口</button><button data-login="check">检查登录</button><button data-login="close" ${login.window_open ? '' : 'disabled'}>完成登录</button></section>` : '';
  const scanText = `当前扫描：${escapeHtml(scan.series_name || '无')} · 来源：${escapeHtml(scan.source || source)} · 状态：${escapeHtml(scan.status || 'idle')} · 当前页：${scan.current_page || scan.page || 0} · 发现：${scan.discovered || 0} · 处理：${scan.processed_count || scan.processed || 0} · 新磁链：${scan.new_magnets || 0} · 失败：${scan.failures || 0}`;
  return `<section class="source-section" data-source-section="${source}">${source === 'javdb' ? '<h2 id="sourcesTitle">来源管理</h2>' : ''}<h3>${label}</h3>${loginCard}<section class="source-status-card" data-scan-status="${source}">${scanText}</section>${sourceForm(source,label)}<div class="source-cards">${rows.map(sourceCard).join('') || `<p class="source-empty">尚未配置 ${label} 系列。</p>`}</div></section>`;
}
async function renderSources() {
  if (sourceOpBusy) return;
  const content = $('#sourceContent');
  content.innerHTML = '<p class="source-loading">正在读取来源配置…</p>';
  try { content.innerHTML = await sourcePanel('javdb', 'JavDB') + await sourcePanel('jphoo', 'JPHOO'); }
  catch (error) { content.innerHTML = `<p class="source-error">${escapeHtml(error.message)}</p>`; showToast(error.message); }
}
function openSources() { sourceLastTrigger = document.activeElement; $('#openSources').setAttribute('aria-current','page'); $('#sourceOverlay').hidden = false; document.body.style.overflow = 'hidden'; renderSources().then(() => $('#closeSources').focus()); if (!sourcePollTimer) sourcePollTimer = setInterval(refreshSourceStatuses, 3000); }
function closeSources() { $('#sourceOverlay').hidden = true; $('#openSources').removeAttribute('aria-current'); document.body.style.overflow = ''; clearInterval(sourcePollTimer); sourcePollTimer = null; sourceLastTrigger?.focus(); }
async function refreshSourceStatuses() {
  if ($('#sourceOverlay').hidden || sourceOpBusy || document.activeElement?.closest('.source-form')) return;
  try {
    for (const source of ['javdb','jphoo']) {
      const scan = await request(`/api/sources/${source}/scan`);
      const box = $(`[data-scan-status="${source}"]`);
      if (box) box.textContent = `当前扫描：${scan.series_name || '无'} · 来源：${scan.source || source} · 状态：${scan.status || 'idle'} · 当前页：${scan.current_page || scan.page || 0} · 发现：${scan.discovered || 0} · 处理：${scan.processed_count || scan.processed || 0} · 新磁链：${scan.new_magnets || 0} · 失败：${scan.failures || 0}`;
    }
  } catch (_) { /* 保留当前界面，下一次轮询重试 */ }
}
async function sourceAction(button, work) {
  if (sourceOpBusy) return; sourceOpBusy = true; button.disabled = true;
  try { await work(); await renderSources(); } catch (error) { showToast(error.message); button.disabled = false; } finally { sourceOpBusy = false; }
}
$('#openSources').addEventListener('click', openSources);
$('#closeSources').addEventListener('click', closeSources);
$('#sourceOverlay').addEventListener('click', event => { if (event.target === $('#sourceOverlay')) closeSources(); });
$('#sourceContent').addEventListener('submit', event => {
  const form = event.target, source = form.dataset.sourceForm; if (!source) return; event.preventDefault();
  sourceAction(form.querySelector('[type="submit"]'), async () => { await request(`/api/sources/${source}`, {method:'POST', body:JSON.stringify(sourcePayload(form,source))}); showToast('来源配置已保存'); });
});
$('#sourceContent').addEventListener('click', event => {
  const button = event.target.closest('button'); if (!button) return;
  const source = button.dataset.source;
  if (button.dataset.login) return sourceAction(button, () => request(`/api/sources/jphoo/login/${button.dataset.login}`, {method:'POST',body:'{}'}));
  if (button.dataset.cancelEdit) { const form=button.closest('form'); form.reset(); delete form.dataset.editId; button.hidden=true; form.querySelector('[data-form-title]').textContent=`添加 ${form.dataset.sourceForm === 'jphoo' ? 'JPHOO' : 'JavDB'} 系列`; return; }
  if (!source) return;
  if (button.dataset.edit) return request(`/api/sources/${source}`).then(rows => { const item=rows.find(row=>String(row.id)===button.dataset.edit); const form=$(`[data-source-form="${source}"]`); form.dataset.editId=item.id; form.name.value=item.name; form.url.value=item.url; form.enabled.checked=Boolean(item.enabled); if(form.profile_dir) form.profile_dir.value=item.profile_dir||''; form.querySelector('[data-form-title]').textContent=`编辑 ${item.name}`; form.querySelector('[data-cancel-edit]').hidden=false; form.scrollIntoView({behavior:'smooth',block:'center'}); }).catch(error => showToast(error.message));
  if (button.dataset.delete) return sourceAction(button, async () => { if (!window.confirm('确认删除这个来源系列配置吗？')) return; await request(`/api/sources/${source}/${button.dataset.delete}`,{method:'DELETE'}); showToast('已删除来源系列'); });
  if (button.dataset.toggle) return sourceAction(button, async () => { const item=(await request(`/api/sources/${source}`)).find(row=>String(row.id)===button.dataset.toggle); await request(`/api/sources/${source}`,{method:'POST',body:JSON.stringify({series_id:item.id,name:item.name,url:item.url,enabled:button.dataset.enabled==='true',profile_dir:item.profile_dir||''})}); });
  const action = button.dataset.scan ? 'scan' : button.dataset.continue ? 'continue' : button.dataset.stop ? 'stop' : '';
  const id = button.dataset.scan || button.dataset.continue || button.dataset.stop;
  if (action) sourceAction(button, () => request(`/api/sources/${source}/${id}/${action}`, {method:'POST',body:'{}'}));
});

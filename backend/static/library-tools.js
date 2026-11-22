// 浏览偏好与主题属于界面；更新、收藏和结果始终读取 SQLite。
import { monthlyUpdateReminder } from './update-reminder.js';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const STATUS = {
  idle: '尚未开始',
  pending: '等待更新',
  starting: '准备中',
  running: '正在更新',
  stopping: '正在停止',
  completed: '已完成',
  stopped: '已停止',
  failed: '未完成',
  needs_attention: '需要处理',
  interrupted: '上次中断',
  retrying: '正在重试',
};

const FILTERS = {
  q: 'searchInput',
  studio: 'studioFilter',
  series: 'seriesFilter',
  actress: 'actressFilter',
  source: 'sourceFilter',
  has_magnet: 'magnetFilter',
  date_from: 'dateFrom',
  date_to: 'dateTo',
  duration: 'durationFilter',
  missing: 'missingFilter',
  sort: 'sortFilter',
};

const EXTRA_FILTERS = [
  'studio',
  'actress',
  'source',
  'has_magnet',
  'duration',
  'missing',
  'date_from',
  'date_to',
];

const shortDate = (value) => (value ? String(value).slice(0, 10) : '尚无记录');

function isTypingTarget(target) {
  if (!target || !(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

export function createLibraryTools(env) {
  const { state, request, escapeHtml: esc, showToast, loadMovies, loadFilters } = env;
  const selected = new Set();
  let selecting = false;
  let lastSelectedIndex = -1;
  let listKey = '';
  let queueTimer = null;
  let badgeTimer = null;
  let detailBusy = false;
  let cachedSources = [];
  let lightboxTrigger = null;

  async function action(button, work) {
    button.disabled = true;
    try {
      await work();
    } catch (error) {
      showToast(error.message);
    } finally {
      button.disabled = false;
    }
  }

  function makeButton(label, work, className = 'text-button') {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.textContent = label;
    button.addEventListener('click', () => action(button, work));
    return button;
  }

  function applyTheme(theme) {
    const root = document.documentElement;
    if (theme === 'dark' || theme === 'light') {
      root.dataset.theme = theme;
    } else {
      delete root.dataset.theme;
    }
    const isDark =
      theme === 'dark' ||
      (!theme && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    const button = $('#toggleTheme');
    if (button) {
      button.textContent = isDark ? '浅色外观' : '深色外观';
      button.setAttribute('aria-pressed', String(isDark));
    }
    const metaTheme = document.querySelector('meta[name="theme-color"]');
    if (metaTheme) {
      metaTheme.content = isDark ? '#1a1c18' : '#f7f6f2';
    }
  }

  function initTheme() {
    let saved = '';
    try {
      saved = localStorage.getItem('yav-theme') || '';
    } catch (_) {
      saved = '';
    }
    applyTheme(saved);
    const button = $('#toggleTheme');
    if (!button) return;
    button.addEventListener('click', () => {
      const currentDark =
        document.documentElement.dataset.theme === 'dark' ||
        (!document.documentElement.dataset.theme &&
          window.matchMedia &&
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      const next = currentDark ? 'light' : 'dark';
      try {
        localStorage.setItem('yav-theme', next);
      } catch (_) {
        // 忽略无痕模式或存储受限
      }
      applyTheme(next);
    });
  }

  function remember() {
    try {
      localStorage.setItem(
        'yav-browse',
        JSON.stringify({
          filters: state.filters,
          quick: state.quick,
          page: state.page,
          pageSize: state.pageSize,
          scroll: window.scrollY,
        }),
      );
    } catch (_) {
      // 忽略存储受限
    }
  }

  function syncControls() {
    for (const [key, id] of Object.entries(FILTERS)) {
      const el = $('#' + id);
      if (!el) continue;
      const value = state.filters[key] || '';
      el.value =
        key === 'actress' && value === state.filterData?.unknown_value ? '未知演员' : value;
    }
    const from = state.filters.date_from || '';
    const to = state.filters.date_to || '';
    const yearSelect = $('#releaseYear');
    if (yearSelect) {
      yearSelect.value =
        from.endsWith('-01-01') && to === from.slice(0, 4) + '-12-31' ? from.slice(0, 4) : '';
    }
    const pageSizeEl = $('#pageSize');
    if (pageSizeEl) {
      pageSizeEl.value = String(state.pageSize);
    }
    $$('[data-quick]').forEach((button) => {
      const active = button.dataset.quick === state.quick;
      button.classList.toggle('is-active', active);
      if (active) button.setAttribute('aria-current', 'page');
      else button.removeAttribute('aria-current');
    });
  }

  function restore() {
    let saved = null;
    try {
      const raw = localStorage.getItem('yav-browse');
      if (raw) saved = JSON.parse(raw);
    } catch (_) {
      return 0;
    }
    if (!saved || typeof saved !== 'object') return 0;
    if (saved.filters && typeof saved.filters === 'object') {
      state.filters = { ...state.filters, ...saved.filters };
    }
    if (typeof saved.quick === 'string') state.quick = saved.quick;
    if (Number.isInteger(saved.page) && saved.page >= 1) state.page = saved.page;
    if (Number.isInteger(saved.pageSize) && saved.pageSize >= 1) state.pageSize = saved.pageSize;
    syncControls();
    return Number.isFinite(saved.scroll) ? saved.scroll : 0;
  }

  function toggleFilters(open) {
    $('#filterFields').hidden = !open;
    $('#toggleFilters').setAttribute('aria-expanded', String(open));
  }

  function triggerExport(format) {
    const params = new URLSearchParams(env.buildQuery());
    params.set('format', format);
    if (selected.size) {
      params.set('ids', [...selected].join(','));
    }
    const link = document.createElement('a');
    link.href = '/api/library/export?' + params;
    link.download = 'yav-library.' + format;
    link.click();
    const menu = $('#exportMenu');
    if (menu) menu.open = false;
  }

  function openLightbox(src, title, triggerEl) {
    if (!src) return;
    lightboxTrigger = triggerEl || document.activeElement;
    const img = $('#lightboxImage');
    img.src = src;
    img.alt = title || '封面大图';
    $('#lightboxOverlay').hidden = false;
    $('#closeLightbox').focus();
  }

  function closeLightbox() {
    const overlay = $('#lightboxOverlay');
    if (!overlay || overlay.hidden) return false;
    overlay.hidden = true;
    $('#lightboxImage').removeAttribute('src');
    lightboxTrigger?.focus?.({ preventScroll: true });
    lightboxTrigger = null;
    return true;
  }

  function setSelecting(value) {
    selecting = value;
    lastSelectedIndex = -1;
    selected.clear();
    renderSelection();
  }

  function toggleMovieSelection(movieId, shiftKey = false) {
    const items = state.result.items || [];
    const index = items.findIndex((item) => item.id === movieId);
    if (shiftKey && lastSelectedIndex >= 0 && index >= 0) {
      const start = Math.min(lastSelectedIndex, index);
      const end = Math.max(lastSelectedIndex, index);
      const shouldSelect = !selected.has(movieId);
      for (let i = start; i <= end; i += 1) {
        if (shouldSelect) selected.add(items[i].id);
        else selected.delete(items[i].id);
      }
    } else if (selected.has(movieId)) {
      selected.delete(movieId);
    } else {
      selected.add(movieId);
    }
    if (index >= 0) lastSelectedIndex = index;
    renderSelection();
  }

  function handleCardClick(event) {
    if (!selecting) return false;
    if (event.target.closest('.movie-selection')) return true;
    const card = event.target.closest('.movie-card');
    if (!card) return false;
    event.preventDefault();
    toggleMovieSelection(Number(card.dataset.id), event.shiftKey);
    return true;
  }

  function renderSelection() {
    document.body.classList.toggle('is-selecting', selecting);
    $('#selectionBar').hidden = !selecting;
    $('#toggleSelection').textContent = selecting ? '取消选择' : '选择';
    $('#selectedCount').textContent = selected.size
      ? `已选 ${selected.size} 部`
      : '点击影片即可多选（支持 Shift 连选）';
    const noSelection = selected.size === 0;
    $('#batchFavorite').disabled = noSelection;
    $('#batchUnfavorite').disabled = noSelection;
    const exportCsvBtn = $('#batchExportCsv');
    const exportTxtBtn = $('#batchExportTxt');
    if (exportCsvBtn) exportCsvBtn.disabled = noSelection;
    if (exportTxtBtn) exportTxtBtn.disabled = noSelection;
    $('#exportHint').textContent = selected.size
      ? `已选的 ${selected.size} 部影片`
      : '当前筛选结果';

    $$('.movie-card').forEach((card) => {
      const id = Number(card.dataset.id);
      card.classList.toggle('is-selected', selected.has(id));
      const existing = card.querySelector('.movie-selection');
      if (!selecting) {
        if (existing) existing.remove();
        return;
      }
      if (existing) {
        existing.querySelector('input').checked = selected.has(id);
        return;
      }
      const label = document.createElement('label');
      label.className = 'movie-selection';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.value = String(id);
      input.checked = selected.has(id);
      input.dataset.selectMovie = '';
      input.setAttribute('aria-label', '选择影片 ' + card.querySelector('.card-title').textContent);
      input.addEventListener('click', (e) => {
        e.stopPropagation();
        if (e.shiftKey) {
          e.preventDefault();
          toggleMovieSelection(id, true);
        }
      });
      input.addEventListener('change', () => {
        const items = state.result.items || [];
        const index = items.findIndex((item) => item.id === id);
        if (input.checked) selected.add(id);
        else selected.delete(id);
        if (index >= 0) lastSelectedIndex = index;
        renderSelection();
      });
      label.append(input);
      card.append(label);
    });
  }

  function renderFilterChips() {
    const names = {
      studio: '厂商',
      actress: '演员',
      source: '来源',
      has_magnet: '磁链',
      duration: '时长',
      missing: '资料',
      date_from: '从',
      date_to: '至',
    };
    const from = state.filters.date_from || '';
    const to = state.filters.date_to || '';
    const year =
      from.endsWith('-01-01') && to === from.slice(0, 4) + '-12-31' ? from.slice(0, 4) : '';
    const active = EXTRA_FILTERS.filter(
      (key) => state.filters[key] && !(year && ['date_from', 'date_to'].includes(key)),
    );
    const count = active.length + (year ? 1 : 0);
    $('#filterCount').textContent = count ? String(count) : '';

    const chips = $('#activeFilters');
    chips.replaceChildren();
    if (year) {
      chips.append(
        makeButton(
          `年份：${year} ×`,
          () => {
            delete state.filters.date_from;
            delete state.filters.date_to;
            state.page = 1;
            syncControls();
            return loadMovies();
          },
          'filter-chip',
        ),
      );
    }
    for (const key of active) {
      const control = $('#' + FILTERS[key]);
      const value =
        control.tagName === 'SELECT' ? control.selectedOptions[0]?.textContent || '' : control.value;
      chips.append(
        makeButton(
          `${names[key]}：${value} ×`,
          () => {
            delete state.filters[key];
            state.page = 1;
            syncControls();
            return loadMovies();
          },
          'filter-chip',
        ),
      );
    }
    if (count) {
      chips.append(makeButton('清除全部', () => env.clearFilters()));
    }
  }

  function afterRender() {
    const key = env.buildQuery();
    if (listKey !== key) {
      selected.clear();
      lastSelectedIndex = -1;
      listKey = key;
    }
    renderSelection();
    renderFilterChips();
    remember();

    const years = state.filterData?.years || [];
    $('#releaseYear').innerHTML =
      '<option value="">全部年份</option>' +
      years.map((year) => `<option value="${year}">${year} 年</option>`).join('');
    syncControls();

    const jumpInput = $('#pageJumpInput');
    if (jumpInput) {
      jumpInput.max = String(Math.max(1, state.result.pages || 1));
      jumpInput.placeholder = String(state.page);
      jumpInput.value = '';
    }

    const scope = $('#updateScope');
    scope.hidden = !state.filters.run_id;
    if (state.filters.run_id) {
      const titleMap = {
        movies: '这次收录的新影片',
        old_magnets: '补到了新磁链的旧影片',
        magnets: '这次新增磁链的影片',
      };
      const title = titleMap[state.filters.update_kind] || '本次更新收录的影片';
      scope.replaceChildren(
        document.createTextNode(title),
        makeButton('返回片库', () => {
          delete state.filters.run_id;
          delete state.filters.update_kind;
          state.page = 1;
          return loadMovies();
        }),
      );
    }
  }

  async function navigate(direction) {
    if (detailBusy || !state.currentMovie) return;
    detailBusy = true;
    try {
      const index = state.result.items.findIndex((movie) => movie.id === state.currentMovie.id);
      let next = index + direction;
      if (next < 0 || next >= state.result.items.length) {
        const page = state.page + direction;
        if (page < 1 || page > state.result.pages) return;
        state.page = page;
        await loadMovies({ silent: true });
        next = direction > 0 ? 0 : state.result.items.length - 1;
      }
      if (state.result.items[next]) {
        await env.openDetail(state.result.items[next].id);
      }
    } finally {
      detailBusy = false;
    }
  }

  async function replaceDetail(movie) {
    state.currentMovie = movie;
    env.renderDetail(movie);
    await loadMovies({ silent: true });
  }

  function afterDetail(movie) {
    const navigation = document.createElement('div');
    navigation.className = 'detail-navigation';
    const previous = makeButton('← 上一部', () => navigate(-1));
    const next = makeButton('下一部 →', () => navigate(1));
    const index = state.result.items.findIndex((item) => item.id === movie.id);
    previous.disabled = index <= 0 && state.page === 1;
    next.disabled = index === state.result.items.length - 1 && state.page === state.result.pages;
    navigation.append(previous, next);
    navigation.hidden = state.result.total <= 1;
    $('.detail-actions').after(navigation);

    const posterImg = $('#detailContent img.detail-poster');
    if (posterImg) {
      posterImg.classList.add('is-zoomable');
      posterImg.title = '点击查看大图';
      posterImg.tabIndex = 0;
      posterImg.setAttribute('role', 'button');
      posterImg.setAttribute('aria-label', '点击放大查看封面');
      const openZoom = () => openLightbox(posterImg.currentSrc || posterImg.src, movie.title, posterImg);
      posterImg.addEventListener('click', openZoom);
      posterImg.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          openZoom();
        }
      });
    }

    const keys = { 厂商: 'studio', 系列: 'series', 演员: 'actress' };
    $$('.detail-fact').forEach((fact) => {
      const key = keys[fact.querySelector('span')?.textContent];
      if (!key) return;
      const values = key === 'actress' ? movie.actresses : movie[key] ? [movie[key]] : [];
      if (!values.length) return;
      const container = fact.querySelector('strong');
      container.replaceChildren();
      for (const value of values) {
        container.append(
          makeButton(
            value,
            async () => {
              env.closeDetail();
              state.filters[key] = value;
              state.quick = 'all';
              state.page = 1;
              syncControls();
              await loadMovies({ scroll: true });
            },
            'fact-link',
          ),
        );
      }
    });

    $$('#editForm input').forEach((input) => {
      if (!movie.manual_fields.includes(input.name)) return;
      const mark = document.createElement('small');
      mark.className = 'manual-marker';
      mark.textContent = '你修改过';
      input.parentElement.append(mark);
    });

    const coverMenu = $('#detailCoverMenu');
    coverMenu.append(
      makeButton('重新获取封面', async () =>
        replaceDetail(
          await request(`/api/movies/${movie.id}/cover`, {
            method: 'POST',
            body: JSON.stringify({ action: 'refresh' }),
          }),
        ),
      ),
    );
    const file = document.createElement('input');
    file.type = 'file';
    file.accept = 'image/png,image/jpeg,image/webp,image/gif';
    file.hidden = true;
    const upload = makeButton('更换本地封面', () => file.click());
    file.addEventListener('change', () => {
      if (!file.files.length) return;
      action(upload, async () => {
        const image = file.files[0];
        if (image.size > 8 * 1024 * 1024) {
          throw new Error('封面请选择 8 MB 以内的图片');
        }
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = () => reject(new Error('图片没有读成功，请重试'));
          reader.readAsDataURL(image);
        });
        const updated = await request(`/api/movies/${movie.id}/cover`, {
          method: 'POST',
          body: JSON.stringify({ data }),
        });
        await replaceDetail(updated);
        showToast('封面已更换');
      });
    });
    coverMenu.append(upload, file);

    renderMagnets(movie);
    renderSourceComparison(movie);
  }

  function renderMagnets(movie) {
    const heading = $('.magnet-heading');
    const select = document.createElement('select');
    select.setAttribute('aria-label', '磁链排序');
    select.innerHTML =
      '<option value="size">按大小</option><option value="newest">最近收录</option>';

    if (movie.magnets.length >= 2) {
      const copyAll = makeButton(
        '复制全部',
        async () => {
          const uniqueLinks = [...new Set(movie.magnets.map((m) => m.magnet).filter(Boolean))];
          await navigator.clipboard.writeText(uniqueLinks.join('\n'));
          copyAll.textContent = `已复制 ${uniqueLinks.length} 条 ✓`;
          showToast(`已复制 ${uniqueLinks.length} 条磁链`);
          setTimeout(() => {
            if (copyAll.isConnected) copyAll.textContent = '复制全部';
          }, 1600);
        },
        'quiet-button copy-all-magnets',
      );
      heading.append(copyAll);
    }

    heading.append(select);

    function render() {
      const magnets = [...movie.magnets];
      if (select.value === 'newest') {
        magnets.sort((a, b) => b.discovered_at.localeCompare(a.discovered_at) || b.id - a.id);
      }
      const previous = $('.magnet-list') || $('.no-magnets');
      if (previous) previous.remove();
      const template = document.createElement('template');
      template.innerHTML = env.magnetList(magnets);
      heading.parentElement.insertBefore(template.content, $('#editForm'));
      $$('.magnet-row').forEach((row, index) => {
        const date = document.createElement('small');
        date.className = 'magnet-discovery';
        date.textContent = shortDate(magnets[index].discovered_at) + ' 收录';
        row.append(date);
      });
      heading.querySelector('p').textContent = movie.magnets.length
        ? `${movie.magnets.length} 条可用磁链`
        : '尚未收录磁链';
    }

    select.addEventListener('change', render);
    render();
  }

  function renderSourceComparison(movie) {
    const compare = document.createElement('details');
    compare.className = 'source-compare';
    compare.id = 'sourceCompare';
    compare.innerHTML = '<summary>参考来源资料</summary><p>选择采用后，会作为你的修改保存。</p>';
    const fields = {
      title: '影片名',
      studio: '厂商',
      series: '系列',
      release_date: '日期',
      duration_minutes: '时长',
      cover_url: '封面',
    };
    for (const source of movie.sources) {
      const section = document.createElement('section');
      const title = document.createElement('h4');
      title.textContent = source.source.toUpperCase();
      section.append(title);
      for (const [key, label] of Object.entries(fields)) {
        const value = key === 'title' ? source.source_title : source[key];
        if (value === null || value === undefined || value === '') continue;
        const row = document.createElement('div');
        row.className = 'compare-row';
        const text = document.createElement('span');
        text.textContent = `${label}：${value}`;
        row.append(text);
        if (String(value) !== String(movie[key] ?? '')) {
          row.append(
            makeButton('采用', async () => {
              const updated = await request(`/api/movies/${movie.id}`, {
                method: 'PATCH',
                body: JSON.stringify({ [key]: value }),
              });
              await replaceDetail(updated);
              $('#editForm').hidden = false;
              $('#sourceCompare').open = true;
              await loadFilters();
            }),
          );
        }
        section.append(row);
      }
      compare.append(section);
    }
    $('#editForm').append(compare);
  }

  function updateQueueBadge(queue) {
    const badge = $('#queueBadge');
    if (!badge) return;
    if (!queue || !queue.id || queue.status === 'idle' || queue.status === 'completed') {
      badge.hidden = true;
      badge.textContent = '';
      badge.className = 'queue-badge';
      return;
    }
    const items = queue.items || [];
    const done = items.filter((item) => item.status === 'completed').length;
    if (queue.running) {
      badge.hidden = false;
      badge.textContent = `更新中 ${done}/${items.length}`;
      badge.className = 'queue-badge is-running';
    } else if (queue.status === 'needs_attention' || queue.status === 'interrupted') {
      badge.hidden = false;
      badge.textContent = queue.status === 'needs_attention' ? '待验证' : '上次中断';
      badge.className = 'queue-badge is-attention';
    } else {
      badge.hidden = true;
    }
  }

  async function pollQueueBadge() {
    clearTimeout(badgeTimer);
    try {
      const queue = await request('/api/library/queue');
      updateQueueBadge(queue);
      if (queue.running) {
        badgeTimer = setTimeout(pollQueueBadge, 4000);
      }
    } catch (_) {
      // 忽略页面退出时的瞬时中断
    }
  }

  async function openTools(preselectIds = null) {
    const dialog = $('#libraryToolsDialog');
    if (!dialog.open) {
      dialog.showModal();
    }
    $('#closeLibraryTools').focus();
    const sources = (
      await Promise.all(['javdb', 'jphoo', 'avfan'].map((source) => request('/api/sources/' + source)))
    ).flat();
    cachedSources = sources.filter((source) => source.enabled);
    const preselect = new Set((preselectIds || []).map(Number));
    $('#queueSources').innerHTML = cachedSources
      .map((source) => {
        const due = monthlyUpdateReminder(source);
        const last = source.last_scanned_at ? shortDate(source.last_scanned_at) : '未更新';
        return `<label class="series-choice${due ? ' is-due' : ''}">
          <input type="checkbox" data-queue-source data-source="${esc(source.source)}" data-due="${due ? '1' : '0'}" value="${source.id}"${preselect.has(source.id) ? ' checked' : ''}>
          <span class="series-choice-name">${esc(source.name)}<em class="series-choice-date">${esc(last)}${due ? ' · 建议更新' : ''}</em></span>
          <small>${source.source.toUpperCase()}</small>
        </label>`;
      })
      .join('');
    await showPanel('updates');
  }

  async function showPanel(name) {
    $$('.tools-tabs button').forEach((button) =>
      button.setAttribute('aria-selected', String(button.dataset.panel === name)),
    );
    $$('#libraryToolsDialog [role=tabpanel]').forEach(
      (panel) => (panel.hidden = panel.id !== 'panel-' + name),
    );
    const renderers = {
      updates: refreshQueue,
      results: renderResults,
      failures: renderFailures,
      backups: renderBackup,
    };
    await renderers[name]();
  }

  async function refreshQueue() {
    clearTimeout(queueTimer);
    const queue = await request('/api/library/queue');
    updateQueueBadge(queue);
    $('#startQueue').disabled = queue.running;
    $('#retryQueue').disabled = queue.running;
    $('#stopQueue').hidden = !queue.running;
    $('#resumeQueue').hidden =
      queue.running || !['stopped', 'interrupted', 'needs_attention'].includes(queue.status);

    const progress = $('#queueProgress');
    progress.replaceChildren();
    if (!queue.id) return;

    const title = document.createElement('h4');
    title.textContent = STATUS[queue.status] || queue.status;
    progress.append(title);

    const completed = queue.items.filter((item) => item.status === 'completed').length;
    const movies = queue.items.reduce((sum, item) => sum + (item.new_movies || 0), 0);
    const magnets = queue.items.reduce((sum, item) => sum + (item.new_magnets || 0), 0);
    const summary = document.createElement('p');
    summary.textContent = `已完成 ${completed} / ${queue.items.length} 个系列 · 新收录 ${movies} 部 · 新磁链 ${magnets} 条`;
    progress.append(summary);

    for (const item of queue.items) {
      const row = document.createElement('div');
      row.className = 'queue-item';
      const name = document.createElement('span');
      name.textContent = item.name;
      const statusEl = document.createElement('span');
      statusEl.textContent =
        item.status === 'running'
          ? `第 ${item.current_page || 1} 页 · 已整理 ${item.processed_count || 0} 部`
          : STATUS[item.status] || item.status;
      row.append(name, statusEl);
      progress.append(row);
    }

    if (queue.last_error) {
      const reason = document.createElement('details');
      reason.className = 'technical-details';
      const heading = document.createElement('summary');
      heading.textContent = '查看暂停原因';
      const text = document.createElement('p');
      text.textContent = queue.last_error;
      reason.append(heading, text);
      progress.append(reason);
    }

    if (queue.running && $('#libraryToolsDialog').open) {
      queueTimer = setTimeout(
        () => refreshQueue().catch((error) => showToast(error.message)),
        1500,
      );
    } else if (queue.running) {
      pollQueueBadge();
    } else if (queue.status === 'completed') {
      await loadFilters();
      await loadMovies({ silent: true });
    }
  }

  async function showResult(run, kind) {
    state.filters = { run_id: String(run.id), update_kind: kind };
    state.quick = 'all';
    state.page = 1;
    syncControls();
    $('#libraryToolsDialog').close();
    await loadMovies({ scroll: true });
  }

  async function renderResults() {
    const scans = await request('/api/library/scans');
    const container = $('#scanHistory');
    container.replaceChildren();
    for (const scan of scans.filter((item) => item.status !== 'idle')) {
      const row = document.createElement('article');
      row.className = 'scan-result';
      const head = document.createElement('div');
      head.className = 'result-title';
      const title = document.createElement('h4');
      title.textContent = scan.name;
      const date = document.createElement('small');
      date.textContent = shortDate(scan.started_at) + ' · ' + (STATUS[scan.status] || scan.status);
      head.append(title, date);
      row.append(head);

      const counts = document.createElement('p');
      counts.textContent = `新收录 ${scan.new_movies} 部影片，补充 ${scan.new_magnets} 条磁链`;
      row.append(counts);

      if (scan.tracked_count) {
        const links = document.createElement('div');
        links.className = 'result-links';
        links.append(
          makeButton('查看新影片', () => showResult(scan, 'movies')),
          makeButton('查看新增磁链', () => showResult(scan, 'magnets')),
        );
        const more = document.createElement('details');
        more.className = 'result-more';
        more.innerHTML = '<summary>更多</summary>';
        more.append(makeButton('仅看旧影片的新磁链', () => showResult(scan, 'old_magnets')));
        links.append(more);
        row.append(links);
      }
      container.append(row);
    }
    if (!container.children.length) {
      container.textContent = '更新后，新收录的影片会出现在这里。';
    }
  }

  async function renderFailures() {
    const failures = await request('/api/library/failures');
    const groups = new Map();
    for (const failure of failures) {
      const key = failure.series_id + ':' + failure.kind;
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(failure);
    }
    const container = $('#scanFailures');
    container.replaceChildren();
    for (const rows of groups.values()) {
      const first = rows[0];
      const row = document.createElement('article');
      row.className = 'failure-row';
      const title = document.createElement('h4');
      title.textContent = first.name;
      const reason = document.createElement('p');
      reason.textContent = `${rows.length} 个页面 · ${first.kind}`;
      row.append(title, reason);

      const details = document.createElement('details');
      details.className = 'technical-details';
      details.innerHTML = '<summary>查看页面</summary>';
      for (const failure of rows) {
        const link = document.createElement('a');
        link.href = failure.source_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        link.textContent = failure.source_url;
        details.append(link);
      }
      const retry = makeButton('重新尝试', async () => {
        await request('/api/library/queue/start', {
          method: 'POST',
          body: JSON.stringify({ ids: [first.series_id], mode: 'retry' }),
        });
        await showPanel('updates');
      });
      if (first.kind.includes('版权')) details.append(retry);
      else row.append(retry);
      row.append(details);
      container.append(row);
    }
    if (!groups.size) {
      container.innerHTML = '<p class="panel-empty">没有需要处理的页面。</p>';
    }
  }

  async function renderBackup() {
    const backup = await request('/api/library/backups');
    $('#backupSummary').textContent = backup.created_at
      ? '最近一次备份：' + shortDate(backup.created_at)
      : '还没有备份，给现在的片库留一份副本吧。';
    $('#backupPath').textContent = backup.latest || backup.directory;
  }

  function init() {
    initTheme();

    $('#toggleFilters').addEventListener('click', () => toggleFilters($('#filterFields').hidden));
    $('#closeFilters').addEventListener('click', () => toggleFilters(false));

    const extraInputs = {
      date_from: 'dateFrom',
      date_to: 'dateTo',
      duration: 'durationFilter',
      missing: 'missingFilter',
      sort: 'sortFilter',
    };
    for (const [key, id] of Object.entries(extraInputs)) {
      $('#' + id).addEventListener('change', () => {
        state.filters[key] = $('#' + id).value;
        state.page = 1;
        loadMovies();
      });
    }

    $('#releaseYear').addEventListener('change', () => {
      const year = $('#releaseYear').value;
      state.filters.date_from = year ? `${year}-01-01` : '';
      state.filters.date_to = year ? `${year}-12-31` : '';
      state.page = 1;
      syncControls();
      loadMovies();
    });

    $('#pageJumpForm')?.addEventListener('submit', (event) => {
      event.preventDefault();
      const input = $('#pageJumpInput');
      const target = Number(input.value);
      const maxPage = Math.max(1, state.result.pages || 1);
      if (!Number.isInteger(target) || target < 1 || target > maxPage) {
        showToast(`请输入 1～${maxPage} 之间的页码`);
        return;
      }
      state.page = target;
      loadMovies({ scroll: true });
    });

    $('#toggleSelection').addEventListener('click', () => setSelecting(!selecting));
    $('#finishSelection').addEventListener('click', () => setSelecting(false));
    $('#selectPage').addEventListener('click', () => {
      state.result.items.forEach((movie) => selected.add(movie.id));
      renderSelection();
    });
    $('#clearSelection').addEventListener('click', () => {
      selected.clear();
      lastSelectedIndex = -1;
      renderSelection();
    });

    for (const [id, favorite] of [
      ['batchFavorite', true],
      ['batchUnfavorite', false],
    ]) {
      $('#' + id).addEventListener('click', () =>
        action($('#' + id), async () => {
          await request('/api/library/favorites', {
            method: 'POST',
            body: JSON.stringify({ ids: [...selected], favorite }),
          });
          setSelecting(false);
          await loadFilters();
          await loadMovies({ silent: true });
          showToast(favorite ? '已加入收藏' : '已取消收藏');
        }),
      );
    }

    for (const [id, format] of [
      ['exportCsv', 'csv'],
      ['exportTxt', 'txt'],
      ['batchExportCsv', 'csv'],
      ['batchExportTxt', 'txt'],
    ]) {
      const btn = $('#' + id);
      if (btn) btn.addEventListener('click', () => triggerExport(format));
    }

    $('#openLibraryTools').addEventListener('click', () =>
      action($('#openLibraryTools'), () => openTools()),
    );
    $('#closeLibraryTools').addEventListener('click', () => $('#libraryToolsDialog').close());
    $('#libraryToolsDialog').addEventListener('close', () => {
      clearTimeout(queueTimer);
      pollQueueBadge();
      $('#openLibraryTools').focus();
    });
    $('#editSourceSettings').addEventListener('click', () => {
      $('#libraryToolsDialog').close();
      env.openSources();
    });

    $$('.tools-tabs [data-panel]').forEach((button) =>
      button.addEventListener('click', () => action(button, () => showPanel(button.dataset.panel))),
    );
    $('.tools-tabs').addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
      event.preventDefault();
      const tabs = $$('.tools-tabs button');
      const index = tabs.indexOf(document.activeElement);
      const next = tabs[(index + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
      next.focus();
      next.click();
    });

    $('#selectDueSeries')?.addEventListener('click', () => {
      const dueInputs = $$('[data-queue-source][data-due="1"]');
      $$('[data-queue-source]').forEach((input) => {
        input.checked = input.dataset.due === '1';
      });
      if (!dueInputs.length) {
        showToast('目前没有满一个月的到期系列');
      }
    });
    $('#selectJavdb').addEventListener('click', () =>
      $$('[data-queue-source]').forEach((input) => {
        input.checked = input.dataset.source === 'javdb';
      }),
    );
    $('#clearQueueSources').addEventListener('click', () =>
      $$('[data-queue-source]').forEach((input) => {
        input.checked = false;
      }),
    );

    for (const [id, operation, mode] of [
      ['startQueue', 'start', 'scan'],
      ['retryQueue', 'start', 'retry'],
      ['resumeQueue', 'resume', 'scan'],
      ['stopQueue', 'stop', 'scan'],
    ]) {
      $('#' + id).addEventListener('click', () =>
        action($('#' + id), async () => {
          const ids = $$('[data-queue-source]:checked').map((input) => Number(input.value));
          await request('/api/library/queue/' + operation, {
            method: 'POST',
            body: JSON.stringify({ ids, mode }),
          });
          await refreshQueue();
        }),
      );
    }

    $('#makeBackup').addEventListener('click', () =>
      action($('#makeBackup'), async () => {
        await request('/api/library/backup', { method: 'POST', body: '{}' });
        await renderBackup();
        showToast('备份已保存');
      }),
    );
    $('#openBackupFolder').addEventListener('click', () =>
      action($('#openBackupFolder'), () =>
        request('/api/library/open-backups', { method: 'POST', body: '{}' }),
      ),
    );

    $('#closeLightbox')?.addEventListener('click', closeLightbox);
    $('#lightboxOverlay')?.addEventListener('click', (event) => {
      if (event.target === $('#lightboxOverlay')) closeLightbox();
    });

    document.addEventListener('keydown', (event) => {
      if (event.altKey || event.ctrlKey || event.metaKey) return;
      if ($('#detailOverlay').hidden || !$('#lightboxOverlay').hidden) return;
      if (isTypingTarget(event.target)) return;
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        navigate(-1);
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        navigate(1);
      } else if (event.key === 'f' || event.key === 'F') {
        event.preventDefault();
        $('#detailFavorite')?.click();
      } else if (event.key === 'e' || event.key === 'E') {
        event.preventDefault();
        $('#editMovie')?.click();
      }
    });

    $('#librarySeriesReminders')?.addEventListener('click', (event) => {
      const filterBtn = event.target.closest('[data-reminder-filter]');
      if (filterBtn) {
        const seriesName = filterBtn.dataset.reminderFilter;
        state.quick = 'all';
        state.filters.series = seriesName;
        state.page = 1;
        syncControls();
        loadMovies({ scroll: true });
        return;
      }
      const updateBtn = event.target.closest('[data-reminder-update]');
      if (updateBtn) {
        const seriesId = Number(updateBtn.dataset.reminderUpdate);
        action(updateBtn, () => openTools([seriesId]));
      }
    });

    let scrollTimer;
    window.addEventListener(
      'scroll',
      () => {
        clearTimeout(scrollTimer);
        scrollTimer = setTimeout(remember, 300);
      },
      { passive: true },
    );

    pollQueueBadge();
  }

  return {
    init,
    restore,
    afterRender,
    afterDetail,
    remember,
    syncControls,
    handleCardClick,
    closeLightbox,
    openTools,
  };
}

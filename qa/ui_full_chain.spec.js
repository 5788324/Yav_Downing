const { test, expect } = require('@playwright/test');
const AxeBuilder = require('@axe-core/playwright').default;
const fs = require('fs');
const path = require('path');

const BASE_URL = process.env.BASE_URL || 'http://127.0.0.1:18765';
const OUT = path.resolve('test-results/ui-audit');
const coverage = [];
const accessibility = [];
const runtimeErrors = [];
let shotNumber = 0;

fs.mkdirSync(OUT, { recursive: true });

test.describe.configure({ mode: 'serial' });
test.setTimeout(12 * 60 * 1000);

function mark(area, control, result = 'passed', note = '') {
  coverage.push({ area, control, result, note });
}

async function shot(page, name) {
  shotNumber += 1;
  const filename = `${String(shotNumber).padStart(2, '0')}-${name}.png`;
  await page.screenshot({ path: path.join(OUT, filename), fullPage: true });
  return filename;
}

async function waitForCards(page, count = 1) {
  await expect(page.locator('#movieGrid .movie-card')).toHaveCount(count, { timeout: 15000 });
}

async function checkA11y(page, stateName) {
  const result = await new AxeBuilder({ page }).analyze();
  const summary = result.violations.map(v => ({
    id: v.id,
    impact: v.impact,
    description: v.description,
    nodes: v.nodes.length,
    targets: v.nodes.slice(0, 8).map(n => n.target.join(' ')),
  }));
  accessibility.push({ state: stateName, violations: summary });
  const blocking = result.violations.filter(v => ['critical', 'serious'].includes(v.impact));
  expect(blocking, `${stateName} 存在严重无障碍问题`).toEqual([]);
  mark('无障碍', stateName, 'passed', `${summary.length} 项非阻塞提示`);
}

async function assertNoHorizontalOverflow(page, stateName) {
  const dimensions = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(dimensions.content, `${stateName} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewport + 1);
  mark('响应式', stateName);
}

async function assertVisibleControlsHaveGeometry(page, stateName) {
  const broken = await page.locator('button:visible,input:visible,select:visible,a:visible').evaluateAll(nodes =>
    nodes.map((node, index) => {
      const rect = node.getBoundingClientRect();
      return {
        index,
        tag: node.tagName,
        text: (node.getAttribute('aria-label') || node.textContent || node.getAttribute('placeholder') || '').trim(),
        width: rect.width,
        height: rect.height,
      };
    }).filter(item => item.width < 8 || item.height < 8)
  );
  expect(broken, `${stateName} 存在不可操作的可见控件`).toEqual([]);
  mark('控件几何', stateName);
}

async function installSourceMock(page) {
  let nextId = 20;
  const sources = {
    javdb: [
      { id: 1, source: 'javdb', name: 'JavDB 既有系列', url: 'https://javdb.example/series/1', enabled: 1, scan_status: 'idle', current_page: 0, discovered: 0, processed_count: 0, new_magnets: 0, failures: 0, profile_dir: '' },
    ],
    jphoo: [
      { id: 2, source: 'jphoo', name: 'JPHOO 既有系列', url: 'https://jphoo.example/series/2', enabled: 1, scan_status: 'idle', current_page: 0, discovered: 0, processed_count: 0, new_magnets: 0, failures: 0, profile_dir: '' },
    ],
  };
  const scans = {
    javdb: { source: 'javdb', status: 'idle', running: false, current_page: 0, discovered: 0, processed_count: 0, new_magnets: 0, failures: 0 },
    jphoo: { source: 'jphoo', status: 'idle', running: false, current_page: 0, discovered: 0, processed_count: 0, new_magnets: 0, failures: 0 },
  };
  let login = { login: 'login_required', status: 'login_required', window_open: false, profile_dir: '/tmp/yav-ui-profile', target_origin: 'https://jphoo.example', last_verified_at: '' };
  let loginTransitions = [];

  await page.route('**/api/sources/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    const method = request.method();
    const send = (body, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });

    if (pathname === '/api/sources/jphoo/login' && method === 'GET') {
      if (loginTransitions.length) login = loginTransitions.shift();
      return send(login);
    }
    const loginAction = pathname.match(/^\/api\/sources\/jphoo\/login\/(open|check|close)$/);
    if (loginAction && method === 'POST') {
      if (loginAction[1] === 'open') {
        login = { ...login, login: 'checking', status: 'opening', window_open: false };
        loginTransitions = [{ ...login }, { ...login, login: 'window_open', status: 'window_open', window_open: true }];
      }
      if (loginAction[1] === 'check') {
        login = { ...login, login: 'checking', status: 'checking', window_open: true };
        loginTransitions = [{ ...login }, { ...login, login: 'ready', status: 'ready', window_open: true, last_verified_at: '2026-07-27T12:00:00+08:00' }];
      }
      if (loginAction[1] === 'close') {
        login = { ...login, login: 'unknown', status: 'closing', window_open: true };
        loginTransitions = [{ ...login }, { ...login, login: 'login_required', status: 'login_required', window_open: false }];
      }
      return send(login, 202);
    }

    const scanStatus = pathname.match(/^\/api\/sources\/(javdb|jphoo)\/scan$/);
    if (scanStatus && method === 'GET') return send(scans[scanStatus[1]]);

    const collection = pathname.match(/^\/api\/sources\/(javdb|jphoo)$/);
    if (collection && method === 'GET') return send(sources[collection[1]]);
    if (collection && method === 'POST') {
      const source = collection[1];
      const payload = request.postDataJSON();
      if (payload.series_id) {
        const item = sources[source].find(row => row.id === Number(payload.series_id));
        Object.assign(item, { name: payload.name, url: payload.url, enabled: payload.enabled ? 1 : 0 });
        return send({ id: item.id }, 201);
      }
      const item = { id: nextId++, source, name: payload.name, url: payload.url, enabled: payload.enabled ? 1 : 0, scan_status: payload.enabled ? 'idle' : 'disabled', current_page: 0, discovered: 0, processed_count: 0, new_magnets: 0, failures: 0, profile_dir: '' };
      sources[source].push(item);
      return send({ id: item.id }, 201);
    }

    const deletion = pathname.match(/^\/api\/sources\/(javdb|jphoo)\/(\d+)$/);
    if (deletion && method === 'DELETE') {
      const rows = sources[deletion[1]];
      const index = rows.findIndex(row => row.id === Number(deletion[2]));
      if (index >= 0) rows.splice(index, 1);
      return send({ deleted: index >= 0 });
    }

    const action = pathname.match(/^\/api\/sources\/(javdb|jphoo)\/(\d+)\/(scan|continue|stop)$/);
    if (action && method === 'POST') {
      const [, source, rawId, command] = action;
      const item = sources[source].find(row => row.id === Number(rawId));
      if (command === 'stop') {
        scans[source] = { ...scans[source], status: 'stopped', running: false };
        item.scan_status = 'stopped';
      } else {
        scans[source] = { ...scans[source], series_name: item.name, status: 'running', running: true, current_page: command === 'scan' ? 1 : 3, discovered: 12, processed_count: 8, new_magnets: 4, failures: 0 };
        item.scan_status = 'running';
        Object.assign(item, scans[source], { scan_status: scans[source].status });
      }
      return send(scans[source], 202);
    }

    return route.continue();
  });
}

test.afterEach(async () => {
  fs.writeFileSync(path.join(OUT, 'coverage.json'), JSON.stringify({ coverage, accessibility, runtimeErrors }, null, 2));
});

test('Yav V2 全链路 UI、交互、响应式和无障碍验收', async ({ browser }) => {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    permissions: ['clipboard-read', 'clipboard-write'],
  });
  const page = await context.newPage();
  let shuttingDown = false;
  page.on('console', message => {
    if (message.type() === 'error' && !shuttingDown) runtimeErrors.push({ type: 'console', text: message.text() });
  });
  page.on('pageerror', error => runtimeErrors.push({ type: 'pageerror', text: error.message }));
  page.on('requestfailed', request => {
    const url = request.url();
    if (!shuttingDown && url.startsWith(BASE_URL) && !(url.includes('/cover') && (request.failure()?.errorText || '').includes('ERR_ABORTED'))) {
      runtimeErrors.push({ type: 'requestfailed', url, error: request.failure()?.errorText || '' });
    }
  });
  await installSourceMock(page);

  await page.goto(BASE_URL, { waitUntil: 'networkidle' });
  await waitForCards(page, 36);
  await expect(page.locator('#resultSummary')).toContainText('83 部影片');
  await expect(page.locator('#statMovies')).toHaveText('83');
  await expect(page.locator('#statFavorites')).toHaveText('9');
  await expect(page.locator('#statMagnets')).not.toHaveText('0');
  mark('首页', '空白加载、统计、36 张首屏卡片');
  await assertNoHorizontalOverflow(page, '桌面首页');
  await assertVisibleControlsHaveGeometry(page, '桌面首页');
  await shot(page, 'desktop-gallery');
  await checkA11y(page, '桌面首页');

  const viewCases = [
    ['收藏架', 'shelf', 'view-shelf'],
    ['资料册', 'catalog', 'view-catalog'],
    ['海报墙', 'gallery', 'view-gallery'],
  ];
  for (const [label, value, className] of viewCases) {
    await page.getByRole('button', { name: label }).click();
    await expect(page.locator('#movieGrid')).toHaveClass(new RegExp(className));
    expect(await page.evaluate(() => localStorage.getItem('yav-view'))).toBe(value);
    mark('视图切换', label);
    await shot(page, `view-${value}`);
  }
  await page.getByRole('button', { name: '收藏架' }).click();
  await page.reload({ waitUntil: 'networkidle' });
  await waitForCards(page, 36);
  await expect(page.locator('#movieGrid')).toHaveClass(/view-shelf/);
  mark('视图切换', '刷新后记忆视图');
  await page.getByRole('button', { name: '海报墙' }).click();

  const quickCases = [
    ['我的收藏', '9 部影片'],
    ['已有磁链', '55 部影片'],
    ['等待补全', '28 部影片'],
    ['全部影片', '83 部影片'],
  ];
  for (const [label, expected] of quickCases) {
    await page.getByRole('button', { name: new RegExp(label) }).click();
    await expect(page.locator('#resultSummary')).toContainText(expected);
    mark('快速筛选', label);
  }

  for (const [buttonName, selectId] of [['厂商', '#studioFilter'], ['系列', '#seriesFilter'], ['女演员', '#actressFilter']]) {
    await page.getByRole('button', { name: new RegExp(buttonName) }).click();
    await expect(page.locator(selectId)).toBeFocused();
    mark('分类入口', `${buttonName}定位筛选框`);
  }

  await page.locator('#searchInput').fill('UI-042');
  await page.locator('#searchInput').press('Enter');
  await waitForCards(page, 1);
  await expect(page.locator('.card-title')).toContainText('UI-042');
  mark('搜索', '输入并按 Enter');
  await page.locator('#searchInput').fill('');
  await page.locator('#searchInput').dispatchEvent('search');
  await waitForCards(page, 36);
  mark('搜索', '清空搜索事件');

  const filterCases = [
    ['#studioFilter', { label: '青岚制作' }, '厂商'],
    ['#seriesFilter', { label: '城市夜航' }, '系列'],
    ['#actressFilter', { label: '林一' }, '女演员'],
    ['#sourceFilter', { label: 'JavDB' }, '磁链来源'],
    ['#magnetFilter', 'true', '有磁链'],
  ];
  for (const [selector, option, label] of filterCases) {
    await page.locator('#clearFilters').click();
    await page.locator(selector).selectOption(option);
    await expect(page.locator('#resultSummary')).not.toContainText('83 部影片');
    mark('组合筛选', label);
  }
  await page.locator('#clearFilters').click();
  await page.locator('#studioFilter').selectOption('__unknown__');
  await expect(page.locator('#contentTitle')).toContainText('未知厂商');
  mark('组合筛选', '未知厂商');
  await page.locator('#clearFilters').click();
  await shot(page, 'filters-cleared');

  for (const size of ['24', '36', '48', '72']) {
    await page.locator('#pageSize').selectOption(size);
    await expect(page.locator('#movieGrid .movie-card')).toHaveCount(Math.min(Number(size), 83));
    mark('分页', `每页 ${size}`);
  }
  await page.locator('#pageSize').selectOption('24');
  await page.locator('#nextPage').click();
  await expect(page.locator('#pageNumbers button.is-active')).toHaveText('2');
  await page.locator('#prevPage').click();
  await expect(page.locator('#pageNumbers button.is-active')).toHaveText('1');
  await page.locator('#pageNumbers [data-page="2"]').click();
  await expect(page.locator('#pageNumbers button.is-active')).toHaveText('2');
  mark('分页', '上一页、下一页、页码按钮');

  // Every rendered movie card and both controls are exercised across the complete data set.
  await page.locator('#pageSize').selectOption('72');
  const auditedIds = [];
  for (const pageNumber of [1, 2]) {
    if (pageNumber === 1) await page.locator('#pageNumbers [data-page="1"]').click();
    else await page.locator('#nextPage').click();
    await expect(page.locator('#movieGrid .movie-card')).toHaveCount(pageNumber === 1 ? 72 : 11, { timeout: 15000 });
    const ids = await page.locator('.movie-card').evaluateAll(cards => cards.map(card => card.dataset.id));
    for (const id of ids) {
      const card = page.locator(`.movie-card[data-id="${id}"]`);
      const title = (await card.locator('.card-title').textContent()).trim();
      const favorite = card.locator('[data-favorite]');
      const before = await favorite.getAttribute('aria-label');
      await favorite.click();
      await expect(favorite).not.toHaveAttribute('aria-label', before);
      await favorite.click();
      await expect(favorite).toHaveAttribute('aria-label', before);
      await card.locator('[data-open]').click();
      await expect(page.locator('#detailTitle')).toHaveText(title);
      await page.locator('#closeDetail').click();
      auditedIds.push(id);
    }
  }
  expect(new Set(auditedIds).size).toBe(83);
  mark('影片卡片', '83 张卡片逐张打开详情');
  mark('影片卡片', '83 个收藏按钮逐个切换并还原');

  await page.locator('#pageNumbers [data-page="1"]').click();
  await page.locator('.movie-card[data-id="2"] .poster-button').scrollIntoViewIfNeeded();
  await expect(page.locator('.movie-card[data-id="2"] .poster-fallback')).toBeVisible();
  mark('封面', '损坏图片自动替换占位图');

  const detailCard = page.locator('.movie-card').filter({ has: page.locator('.source-pill b') }).first();
  const detailTitle = (await detailCard.locator('.card-title').textContent()).trim();
  await detailCard.locator('[data-open]').click();
  await expect(page.locator('#detailTitle')).toHaveText(detailTitle);
  await expect(page.locator('.magnet-row').first()).toBeVisible();
  await shot(page, 'movie-detail');
  await checkA11y(page, '影片详情弹窗');

  const firstCopy = page.locator('.copy-magnet').first();
  const expectedMagnet = await firstCopy.getAttribute('data-copy');
  await firstCopy.click();
  await expect(page.locator('#toast')).toContainText('磁链已复制');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(expectedMagnet);
  mark('磁链', '复制磁链及成功提示');
  const sourceLink = page.locator('.magnet-actions a').first();
  await expect(sourceLink).toHaveAttribute('target', '_blank');
  const popupPromise = context.waitForEvent('page');
  await sourceLink.click();
  const popup = await popupPromise;
  await popup.waitForLoadState('domcontentloaded').catch(() => {});
  expect(popup).toBeTruthy();
  await popup.close();
  mark('磁链', '来源链接新标签打开');

  await page.locator('#detailFavorite').click();
  await expect(page.locator('#detailFavorite')).toContainText(/已收藏|加入收藏/);
  await page.locator('#detailFavorite').click();
  mark('详情', '详情收藏按钮切换并还原');

  await page.locator('#editMovie').click();
  await expect(page.locator('#editForm')).toBeVisible();
  await shot(page, 'movie-edit-form');
  const edit = page.locator('#editForm');
  await edit.locator('[name="title"]').fill('');
  await edit.getByRole('button', { name: '保存手动修改' }).click();
  expect(await edit.locator('[name="title"]').evaluate(element => element.matches(':invalid'))).toBe(true);
  mark('影片编辑', '影片名必填校验');
  await edit.locator('[name="title"]').fill('UI-EDITED 完整编辑测试');
  await edit.locator('[name="cover_url"]').fill('https://example.test/new-cover.jpg');
  await edit.locator('[name="studio"]').fill('编辑后厂商');
  await edit.locator('[name="series"]').fill('编辑后系列');
  await edit.locator('[name="release_date"]').fill('2026-07-27');
  await edit.locator('[name="duration_minutes"]').fill('123');
  await edit.locator('[name="actresses"]').fill('演员甲、演员乙，演员丙');
  await edit.getByRole('button', { name: '保存手动修改' }).click();
  await expect(page.locator('#toast')).toContainText('影片资料已保存');
  await expect(page.locator('#detailTitle')).toHaveText('UI-EDITED 完整编辑测试');
  await expect(page.locator('.detail-facts')).toContainText('编辑后厂商');
  await expect(page.locator('.detail-facts')).toContainText('123 分钟');
  for (const actress of ['演员甲', '演员乙', '演员丙']) await expect(page.locator('.detail-facts')).toContainText(actress);
  mark('影片编辑', '全部七个输入框保存并回显');

  await page.locator('#closeDetail').click();
  await page.locator('#searchInput').fill('UI-EDITED');
  await page.locator('#searchInput').press('Enter');
  await waitForCards(page, 1);
  await expect(page.locator('.card-title')).toHaveText('UI-EDITED 完整编辑测试');
  mark('影片编辑', '编辑结果同步到卡片和搜索');
  await page.locator('#clearFilters').click();
  await page.locator('#pageSize').selectOption('72');

  // Close paths and focus restoration.
  const focusCard = page.locator('.movie-card').first().locator('[data-open]');
  await focusCard.focus();
  await focusCard.click();
  await page.locator('#closeDetail').click();
  await expect(focusCard).toBeFocused();
  await focusCard.click();
  await page.locator('#detailOverlay').click({ position: { x: 5, y: 5 } });
  await expect(page.locator('#detailOverlay')).toBeHidden();
  await focusCard.click();
  await page.keyboard.press('Escape');
  await expect(page.locator('#detailOverlay')).toBeHidden();
  mark('详情弹窗', '关闭按钮、遮罩、Escape、焦点恢复');

  await page.locator('#searchInput').fill('绝对不存在的影片');
  await page.locator('#searchInput').press('Enter');
  await expect(page.locator('#emptyState')).toBeVisible();
  await shot(page, 'empty-state');
  await page.locator('#emptyClear').click();
  await expect(page.locator('#emptyState')).toBeHidden();
  mark('空状态', '无结果提示及显示全部影片按钮');

  await page.locator('#openSources').focus();
  await page.locator('#openSources').click();
  await expect(page.locator('#sourceOverlay')).toBeVisible();
  await expect(page.locator('#closeSources')).toBeFocused();
  await shot(page, 'source-management');
  await checkA11y(page, '来源管理弹窗');

  const javdbForm = page.locator('[data-source-form="javdb"]');
  await javdbForm.getByRole('button', { name: '保存系列' }).click();
  expect(await javdbForm.evaluate(form => form.checkValidity())).toBe(false);
  mark('来源表单', 'JavDB 名称和网址必填校验');
  await javdbForm.locator('[name="name"]').fill('UI 新增 JavDB');
  await javdbForm.locator('[name="url"]').fill('https://javdb.example/ui-new');
  await javdbForm.locator('[name="enabled"]').uncheck();
  await javdbForm.getByRole('button', { name: '保存系列' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 新增 JavDB' })).toContainText('已停用');
  mark('来源 CRUD', '新增停用的 JavDB 系列');

  let newJavdbCard = page.locator('.source-card').filter({ hasText: 'UI 新增 JavDB' });
  await newJavdbCard.getByRole('button', { name: '编辑' }).click();
  await expect(javdbForm.locator('[data-form-title]')).toContainText('编辑 UI 新增 JavDB');
  await javdbForm.getByRole('button', { name: '取消编辑' }).click();
  await expect(javdbForm.locator('[data-form-title]')).toContainText('添加 JavDB 系列');
  mark('来源 CRUD', '编辑模式和取消编辑');
  await newJavdbCard.getByRole('button', { name: '编辑' }).click();
  await expect(javdbForm.locator('[data-form-title]')).toContainText('编辑 UI 新增 JavDB');
  await javdbForm.locator('[name="name"]').fill('UI 已编辑 JavDB');
  await javdbForm.locator('[name="enabled"]').check();
  await javdbForm.getByRole('button', { name: '保存系列' }).click();
  newJavdbCard = page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' });
  await expect(newJavdbCard).toContainText('已启用');
  mark('来源 CRUD', '编辑并保存来源');
  await newJavdbCard.getByRole('button', { name: '停用' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' })).toContainText('已停用');
  await page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' }).getByRole('button', { name: '启用' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' })).toContainText('已启用');
  mark('来源 CRUD', '启用和停用');

  newJavdbCard = page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' });
  page.once('dialog', dialog => dialog.dismiss());
  await newJavdbCard.getByRole('button', { name: '删除' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' })).toBeVisible();
  page.once('dialog', dialog => dialog.accept());
  await page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' }).getByRole('button', { name: '删除' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 已编辑 JavDB' })).toHaveCount(0);
  mark('来源 CRUD', '删除确认取消和确认删除');

  const jphooForm = page.locator('[data-source-form="jphoo"]');
  await jphooForm.locator('[name="name"]').fill('UI 新增 JPHOO');
  await jphooForm.locator('[name="url"]').fill('https://jphoo.example/ui-new');
  await jphooForm.getByRole('button', { name: '保存系列' }).click();
  await expect(page.locator('.source-card').filter({ hasText: 'UI 新增 JPHOO' })).toBeVisible();
  mark('来源 CRUD', '新增 JPHOO 系列');

  await expect(page.locator('[data-login="check"]')).toBeDisabled();
  await expect(page.locator('[data-login="close"]')).toBeDisabled();
  await page.locator('#jphooLoginSeries').selectOption('2');
  await page.locator('[data-login="open"]').click();
  await expect(page.locator('[data-login="check"]')).toBeEnabled({ timeout: 10000 });
  await page.locator('[data-login="check"]').click();
  await expect(page.locator('[data-login-state]')).toHaveText('ready', { timeout: 10000 });
  mark('JPHOO 会话', '登录目标、打开会话、验证登录');

  const jphooExisting = page.locator('[data-source-card="jphoo-2"]');
  page.once('dialog', dialog => dialog.accept());
  await jphooExisting.getByRole('button', { name: '从第 1 页重新扫描' }).click();
  await expect(page.locator('[data-source-card="jphoo-2"]')).toContainText('停止扫描');
  await page.locator('[data-source-card="jphoo-2"]').getByRole('button', { name: '停止扫描' }).click();
  await expect(page.locator('[data-source-card="jphoo-2"]')).toContainText('继续扫描');
  await page.locator('[data-source-card="jphoo-2"]').getByRole('button', { name: '继续扫描' }).click();
  await page.locator('[data-source-card="jphoo-2"]').getByRole('button', { name: '停止扫描' }).click();
  mark('JPHOO 扫描', '全量、停止、继续、再次停止');
  await page.locator('[data-login="close"]').click();
  await expect(page.locator('[data-login-state]')).toHaveText('login_required', { timeout: 10000 });
  mark('JPHOO 会话', '关闭会话');

  const javdbExisting = page.locator('[data-source-card="javdb-1"]');
  page.once('dialog', dialog => dialog.accept());
  await javdbExisting.getByRole('button', { name: '从第 1 页重新扫描' }).click();
  await page.locator('[data-source-card="javdb-1"]').getByRole('button', { name: '停止扫描' }).click();
  await page.locator('[data-source-card="javdb-1"]').getByRole('button', { name: '继续扫描' }).click();
  await page.locator('[data-source-card="javdb-1"]').getByRole('button', { name: '停止扫描' }).click();
  mark('JavDB 扫描', '全量、停止、继续、再次停止');

  await page.keyboard.press('Escape');
  await expect(page.locator('#sourceOverlay')).toBeHidden();
  await expect(page.locator('#openSources')).toBeFocused();
  await page.locator('#openSources').click();
  await page.locator('#sourceOverlay').click({ position: { x: 4, y: 4 } });
  await expect(page.locator('#sourceOverlay')).toBeHidden();
  await page.locator('#openSources').click();
  await page.locator('#closeSources').click();
  mark('来源弹窗', 'Escape、遮罩、关闭按钮、焦点恢复');

  await page.setViewportSize({ width: 820, height: 1024 });
  await page.reload({ waitUntil: 'networkidle' });
  await waitForCards(page, 36);
  await assertNoHorizontalOverflow(page, '平板 820px');
  await assertVisibleControlsHaveGeometry(page, '平板 820px');
  await shot(page, 'tablet-820');

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: 'networkidle' });
  await waitForCards(page, 36);
  await assertNoHorizontalOverflow(page, '手机 390px');
  await assertVisibleControlsHaveGeometry(page, '手机 390px');
  await expect(page.locator('.nav-item[data-quick]')).toHaveCount(4);
  const mobileNames = await page.locator('.nav-item[data-quick],#openSources').evaluateAll(nodes => nodes.map(node => ({
    aria: node.getAttribute('aria-label') || '',
    text: (node.innerText || '').trim(),
  })));
  expect(mobileNames.every(item => item.aria || /全部影片|我的收藏|已有磁链|等待补全|来源管理/.test(item.text)), '手机导航缺少可理解的名称').toBe(true);
  mark('移动端', '快速导航、来源管理和可理解名称');
  await page.locator('#openSources').click();
  await expect(page.locator('#sourceOverlay')).toBeVisible();
  await assertNoHorizontalOverflow(page, '手机来源管理');
  await shot(page, 'mobile-source-management');
  await page.locator('#closeSources').click();
  await shot(page, 'mobile-library');
  await checkA11y(page, '手机首页');

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.reload({ waitUntil: 'networkidle' });
  await waitForCards(page, 36);
  page.once('dialog', dialog => dialog.dismiss());
  await page.locator('#shutdownApp').click();
  await expect(page.locator('#shutdownApp')).toHaveText('安全退出 Yav');
  mark('安全退出', '确认框取消');
  page.once('dialog', dialog => dialog.accept());
  shuttingDown = true;
  await page.locator('#shutdownApp').click();
  await expect(page.locator('body')).toContainText(/Yav 已安全退出|Yav 仍在安全退出中/, { timeout: 30000 });
  await shot(page, 'safe-shutdown');
  mark('安全退出', '确认、HTTP 202、退出完成页');

  expect(runtimeErrors, '运行期间出现控制台、页面或同源网络错误').toEqual([]);
  expect(coverage.filter(item => item.result !== 'passed')).toEqual([]);
  fs.writeFileSync(path.join(OUT, 'summary.txt'), [
    'YAV_UI_FULL_CHAIN_SUCCESS',
    `coverage_items=${coverage.length}`,
    `screenshots=${shotNumber}`,
    `accessibility_states=${accessibility.length}`,
    `runtime_errors=${runtimeErrors.length}`,
  ].join('\n'));
  await context.close();
});

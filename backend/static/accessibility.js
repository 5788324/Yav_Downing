(() => {
  const labels = {
    searchInput: '搜索影片名',
    pageSize: '每页显示数量',
    openSources: '来源管理',
  };

  function applyLabels(root = document) {
    Object.entries(labels).forEach(([id, label]) => {
      const element = document.getElementById(id);
      if (element && !element.getAttribute('aria-label')) element.setAttribute('aria-label', label);
    });

    document.querySelectorAll('[data-quick]').forEach(button => {
      const text = button.querySelector('span:nth-child(2)')?.textContent?.trim();
      if (text) button.setAttribute('aria-label', text);
    });

    root.querySelectorAll?.('[data-source-form]').forEach(form => {
      const source = form.dataset.sourceForm === 'jphoo' ? 'JPHOO' : 'JavDB';
      const name = form.querySelector('input[name="name"]');
      const url = form.querySelector('input[name="url"]');
      if (name) name.setAttribute('aria-label', `${source} 系列名称`);
      if (url) url.setAttribute('aria-label', `${source} 系列网址`);
    });
  }

  applyLabels();
  const sourceContent = document.getElementById('sourceContent');
  if (sourceContent) {
    new MutationObserver(() => applyLabels(sourceContent)).observe(sourceContent, { childList: true, subtree: true });
  }
})();

'use strict';

// Move existing controls intact so their values, IDs and event handlers are retained.
(() => {
  const wrapDetails = (label, elements, before) => {
    const nodes = elements.filter(Boolean);
    if (!nodes.length || !before?.parentNode) return;
    const details = document.createElement('details');
    details.className = 'research-details';
    const summary = document.createElement('summary');
    summary.textContent = label;
    details.append(summary);
    before.parentNode.insertBefore(details, before);
    nodes.forEach(node => details.append(node));
  };
  const profile = document.querySelector('.investment-profile');
  wrapDetails('投资目标与研究假设', [profile], profile);
  wrapDetails('研究选项', [document.querySelector('.research-options'), document.querySelector('.valuation-setup')], document.querySelector('.query-actions'));

  const root = document.documentElement;
  const toggle = document.getElementById('ambient-toggle');
  if (!toggle) return;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const key = 'zhiheng.ui.ambient.v1';
  let enabled = true;
  try { enabled = localStorage.getItem(key) !== 'off'; } catch { /* Storage may be unavailable in private mode. */ }
  const render = () => {
    const paused = !enabled || reduced.matches || document.hidden;
    root.dataset.ambientPaused = String(paused);
    toggle.disabled = reduced.matches;
    toggle.textContent = reduced.matches ? '背景静止' : enabled ? '暂停背景' : '继续背景';
    toggle.setAttribute('aria-pressed', String(!enabled || reduced.matches));
    toggle.setAttribute('aria-label', reduced.matches ? '系统已启用减少动态效果，背景保持静止' : toggle.textContent);
  };
  toggle.addEventListener('click', () => {
    enabled = !enabled;
    try { localStorage.setItem(key, enabled ? 'on' : 'off'); } catch { /* The current session still honors the choice. */ }
    render();
  });
  reduced.addEventListener('change', render);
  document.addEventListener('visibilitychange', render);
  render();
})();

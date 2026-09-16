/* EvalScope 原型交互脚本（轻量，无依赖） */

/* 指标说明 popover：点击 ? 切换；弹层为 position:fixed，按需计算坐标 + 视口夹取，
   避免被 overflow:hidden / overflow:auto 的祖先裁切。 */
function positionExplainPop(wrap) {
  var btn = wrap.querySelector('.explain-btn');
  var pop = wrap.querySelector('.explain-pop');
  if (!btn || !pop) return;
  var GAP = 8, M = 12; // 与按钮间距 / 视口边距
  var b = btn.getBoundingClientRect();
  var pw = pop.offsetWidth, ph = pop.offsetHeight;
  var vw = document.documentElement.clientWidth;
  var vh = document.documentElement.clientHeight;

  // 水平：以按钮为中心，再夹取到视口内
  var left = b.left + b.width / 2 - pw / 2;
  left = Math.max(M, Math.min(left, vw - pw - M));

  // 垂直：默认在按钮下方；若下方放不下则翻到上方
  var top = b.bottom + GAP;
  if (top + ph > vh - M && b.top - GAP - ph > M) top = b.top - GAP - ph;
  top = Math.max(M, Math.min(top, vh - ph - M));

  pop.style.left = Math.round(left) + 'px';
  pop.style.top = Math.round(top) + 'px';
}

function closeAllExplain() {
  document.querySelectorAll('.explain.open').forEach(function (el) { el.classList.remove('open'); });
}

document.addEventListener('click', function (e) {
  var btn = e.target.closest('.explain-btn');
  if (btn) {
    var wrap = btn.closest('.explain');
    var wasOpen = wrap.classList.contains('open');
    closeAllExplain();
    if (!wasOpen) {
      wrap.classList.add('open');
      // 先显示再量取尺寸，确保 offsetWidth/Height 有效
      positionExplainPop(wrap);
    }
    e.stopPropagation();
    return;
  }
  if (e.target.closest('.explain-pop')) return; // 点击说明卡内部不关闭
  closeAllExplain();
});

/* 滚动 / 缩放时跟随按钮重新定位（捕获阶段以监听内部滚动容器） */
function repositionOpenExplain() {
  var wrap = document.querySelector('.explain.open');
  if (wrap) positionExplainPop(wrap);
}
window.addEventListener('scroll', repositionOpenExplain, true);
window.addEventListener('resize', repositionOpenExplain);

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeAllExplain();
    document.querySelectorAll('.scrim[data-open]').forEach(function (el) { el.style.display = 'none'; el.removeAttribute('data-open'); });
  }
});

/* ── 主题（浅色 / 深色）────────────────────────────────────────────────
   决策规则：显式选择（localStorage.es-theme，顶栏按钮写入）
           > 系统偏好（prefers-color-scheme: light）
           > 深色（系统未表态时的默认）。
   未显式选择时实时跟随系统切换；显式选择后不再自动跟随。
   CSS 侧：theme.css「浅色模式」段（token 双块 + 组件级适配）。 */
(function () {
  var KEY = 'es-theme';
  var mql = window.matchMedia ? window.matchMedia('(prefers-color-scheme: light)') : null;

  function systemTheme() { return mql && mql.matches ? 'light' : 'dark'; }
  function storedTheme() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function currentTheme() { return storedTheme() || systemTheme(); }

  function apply(t) {
    document.documentElement.setAttribute('data-theme', t);
    var btn = document.getElementById('es-theme-btn');
    if (btn) {
      btn.classList.toggle('is-light', t === 'light');
      btn.title = t === 'light' ? '切换到深色模式' : '切换到浅色模式';
      btn.setAttribute('aria-label', btn.title);
    }
  }

  function setTheme(t) {
    try { localStorage.setItem(KEY, t); } catch (e) { /* file:// 下可能被拒，忽略 */ }
    apply(t);
  }

  apply(currentTheme());

  if (mql) {
    var onSystemChange = function () { if (!storedTheme()) apply(systemTheme()); };
    if (mql.addEventListener) mql.addEventListener('change', onSystemChange);
    else if (mql.addListener) mql.addListener(onSystemChange); // 旧 Safari
  }

  function initToggle() {
    if (document.getElementById('es-theme-btn')) return;
    var btn = document.createElement('button');
    btn.id = 'es-theme-btn';
    btn.className = 'icon-btn es-theme-btn';
    btn.type = 'button';
    /* 太阳 / 月亮双图标，按当前模式显隐（theme.css 控制显隐） */
    btn.innerHTML =
      '<svg class="ico-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
      '<svg class="ico-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
    btn.addEventListener('click', function () {
      setTheme(document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light');
    });
    var host = document.querySelector('.topbar-right');
    if (host) host.insertBefore(btn, host.firstChild);
    else {
      /* 无顶栏页（落地 / 登录 / 注册）：右上角悬浮 */
      btn.classList.add('es-theme-float');
      document.body.appendChild(btn);
    }
    apply(document.documentElement.getAttribute('data-theme') || currentTheme());
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initToggle);
  else initToggle();
})();

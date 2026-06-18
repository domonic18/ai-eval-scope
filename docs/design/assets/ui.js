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

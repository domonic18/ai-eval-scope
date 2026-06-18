/* EvalScope 原型交互脚本（轻量，无依赖） */

/* 指标说明 popover：点击 ? 切换，点击外部 / Esc 关闭，同时只开一个 */
document.addEventListener('click', function (e) {
  var btn = e.target.closest('.explain-btn');
  var openOne = document.querySelector('.explain.open');
  if (btn) {
    var wrap = btn.closest('.explain');
    var wasOpen = wrap.classList.contains('open');
    document.querySelectorAll('.explain.open').forEach(function (el) { el.classList.remove('open'); });
    if (!wasOpen) wrap.classList.add('open');
    e.stopPropagation();
    return;
  }
  // 点击说明卡内部不关闭
  if (e.target.closest('.explain-pop')) return;
  if (openOne) openOne.classList.remove('open');
});

document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    document.querySelectorAll('.explain.open').forEach(function (el) { el.classList.remove('open'); });
    document.querySelectorAll('.scrim[data-open]').forEach(function (el) { el.style.display = 'none'; el.removeAttribute('data-open'); });
  }
});

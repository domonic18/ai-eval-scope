/* EvalScope 文档站原型脚本（轻量，无依赖，与 ui.js 同风格）
   职责：目录树渲染 / 目录索引卡墙 / 站内搜索（docs.html 主区切换 or 文章页下拉浮层）
        / 文章大纲滚动高亮 / ⌘K 聚焦 / 代码块复制按钮。
   数据单一来源：DOCS_INDEX —— 树、索引卡墙、搜索共用，保证永不发散。
   渲染物样式由本脚本一次性注入（全部走 theme.css 变量，双主题自动适配），
   theme.css 保持零改动。 */

(function () {
  'use strict';

  /* ── 文档索引数据 ───────────────────────────────────────────────
     href 为空 = 原型灰态占位条目（无真实页面，同侧栏死链惯例）。 */
  var DOCS_INDEX = [
    { num: '01', title: '产品简介', group: '开始使用', href: 'index.html', summary: 'EvalScope 是什么，为谁解决什么问题', kw: ['intro', '简介', '产品', 'overview', '平台', '评估'] },
    { num: '02', title: '快速开始', group: '开始使用', href: 'docs-quickstart.html', summary: '安装、配置评测模型 Key、完成第一次评估', kw: ['quickstart', '入门', '上手', 'setup', '安装', 'install', '模型', 'key'] },
    { num: '03', title: '安装与升级', group: '开始使用', href: '', summary: 'uv tool install 与版本升级', kw: ['install', 'uv', 'upgrade', '升级', 'extras', '依赖'] },
    { num: '04', title: '四通道总览', group: '接入指南', href: 'getting-started.html', summary: 'HTTP API / Webhook / MCP / CLI 选型对比', kw: ['integration', '接入', '通道', 'channel', 'http', 'webhook', 'mcp', 'cli', '选型', '对接'] },
    { num: '05', title: 'HTTP API', group: '接入指南', href: '', summary: 'POST /api/v1/jobs 提交评测，轮询结果与速览', kw: ['http', 'api', 'rest', 'jobs', '提交', '轮询', 'polling', '接口'] },
    { num: '06', title: 'Webhook 结果回调', group: '接入指南', href: '', summary: '评估完成后平台主动 POST 你的服务，免轮询', kw: ['webhook', '回调', 'callback', '通知', 'notify', '签名', 'signature'] },
    { num: '07', title: 'MCP 接入', group: '接入指南', href: '', summary: '让 AI 智能体直接提交与查询评测', kw: ['mcp', 'agent', '智能体', 'claude', 'cursor', '工具', 'tool'] },
    { num: '08', title: 'CLI 上报', group: '接入指南', href: '', summary: '评估器本地直跑，结果自动上报平台', kw: ['cli', '命令行', '上报', 'upload', '离线', '批跑'] },
    { num: '09', title: '核心概念', group: '概念', href: '', summary: '组织 / 项目 / 运行 / 样本 / 约束 五级模型', kw: ['concept', '概念', '组织', '项目', '运行', '样本', '约束', '层级'] },
    { num: '10', title: '指标体系', group: '概念', href: '', summary: 'DR / CPR / Reward / CondR 口径与阈值', kw: ['metrics', '指标', 'dr', 'cpr', 'reward', 'condr', '阈值', '口径'] },
    { num: '11', title: '场景包与资产', group: '概念', href: '', summary: '场景包清单与五类资产结构', kw: ['package', '场景包', '资产', 'asset', 'yaml', '清单', '规则集'] },
    { num: '12', title: 'Web 可观测平台', group: '平台', href: '', summary: 'docker-compose 自部署与 API Key 摄取', kw: ['web', '平台', 'docker', '部署', 'deploy', '摄取', 'ingest', 'api key'] },
    { num: '13', title: 'API 摘要', group: '平台', href: 'docs.html#api', summary: '对外 REST 端点速查', kw: ['api', '端点', 'endpoint', 'rest', '速查', '参考', 'reference'] },
    { num: '14', title: 'FAQ', group: '关于', href: '', summary: '常见问题与排查', kw: ['faq', '问题', '排查', 'troubleshoot', 'help'] },
    { num: '15', title: '许可证', group: '关于', href: '', summary: 'MIT 开源许可', kw: ['license', 'mit', '许可', '开源'] }
  ];

  /* 当前文档页（body data-doc-page，对应条目 num；目录首页留空） */
  var PAGE = document.body.getAttribute('data-doc-page') || '';

  /* ── 注入样式（渲染物专属，全部走 CSS 变量） ── */
  var css = [
    'mark { background: var(--accent-soft); color: var(--accent); border-radius: 2px; padding: 0 1px; }',
    '.doc-num { font-family: var(--mono); font-size: 11px; color: var(--text-quaternary); width: 20px; flex-shrink: 0; }',
    '.nav-item.dim, .nav-label.dim { opacity: .32; }',
    '/* 目录索引卡墙（docs.html 主区默认视图） */',
    '.doc-wall { display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px; }',
    '@media (max-width: 920px) { .doc-wall { grid-template-columns: 1fr; } }',
    '.doc-dir-row { display: flex; align-items: center; gap: 12px; padding: 11px 16px; border-bottom: 1px solid var(--border); font-size: 13px; color: var(--text-secondary); transition: background .1s var(--ease); }',
    '.doc-dir-row:last-child { border-bottom: none; }',
    'a.doc-dir-row:hover { background: var(--bg-hover); color: var(--text-primary); }',
    'a.doc-dir-row .doc-arrow { margin-left: auto; opacity: 0; transition: opacity .12s var(--ease); color: var(--accent); flex-shrink: 0; }',
    'a.doc-dir-row:hover .doc-arrow { opacity: 1; }',
    '.doc-dir-row.disabled { color: var(--text-quaternary); cursor: default; }',
    '.doc-dir-row .doc-dir-sum { font-size: 12px; color: var(--text-tertiary); margin-left: auto; padding-left: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '.doc-dir-row.disabled .doc-dir-sum { opacity: .6; }',
    '/* 搜索结果列表（docs.html 搜索态） */',
    '.doc-hit { display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 13.5px; }',
    'a.doc-hit:hover { background: var(--bg-hover); }',
    '.doc-hit .doc-hit-sum { font-size: 12px; color: var(--text-tertiary); margin-left: auto; padding-left: 16px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }',
    '/* 搜索下拉浮层（文章页） */',
    '.doc-search-pop { position: absolute; top: calc(100% + 6px); left: 0; right: 0; z-index: 150; background: var(--bg-elevated); border: 1px solid var(--border-hover); border-radius: var(--r-md); box-shadow: var(--shadow-lg); overflow: hidden; display: none; }',
    '.doc-search-pop.open { display: block; }',
    '.doc-hit.active { background: var(--accent-soft); }',
    '.doc-search-empty { padding: 18px 16px; font-size: 12.5px; color: var(--text-tertiary); text-align: center; }',
    '/* 文章右栏大纲（On this page） */',
    '.doc-toc-link { display: block; padding: 4px 0 4px 12px; font-size: 12.5px; color: var(--text-tertiary); border-left: 2px solid var(--border); transition: all .12s var(--ease); }',
    '.doc-toc-link:hover { color: var(--text-primary); }',
    '.doc-toc-link.active { color: var(--accent); border-left-color: var(--accent); font-weight: 550; }'
  ].join('\n');
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  /* ── 工具 ── */
  function escReg(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }
  function hi(text, q) {
    if (!q) return text;
    return text.replace(new RegExp('(' + escReg(q) + ')', 'ig'), '<mark>$1</mark>');
  }
  function score(it, q) {
    var t = it.title.toLowerCase(), k = (it.kw.join(' ') + ' ' + it.num).toLowerCase(), s = it.summary.toLowerCase();
    if (t.indexOf(q) === 0) return 100;
    if (t.indexOf(q) >= 0) return 80;
    if (k.indexOf(q) >= 0) return 60;
    if (s.indexOf(q) >= 0) return 40;
    return 0;
  }
  function search(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    return DOCS_INDEX.map(function (it) { return { it: it, sc: score(it, q) }; })
      .filter(function (r) { return r.sc > 0; })
      .sort(function (a, b) { return b.sc - a.sc; })
      .map(function (r) { return r.it; });
  }
  function arrowSvg() {
    return '<svg class="doc-arrow" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>';
  }

  /* ── 左侧目录树（#doc-tree 占位） ── */
  function renderTree() {
    var root = document.getElementById('doc-tree');
    if (!root) return;
    var html = '', lastGroup = null;
    DOCS_INDEX.forEach(function (it) {
      if (it.group !== lastGroup) {
        html += '<div class="nav-label" data-group="' + it.group + '">' + it.group + '</div>';
        lastGroup = it.group;
      }
      var inner = '<span class="doc-num">' + it.num + '</span><span>' + it.title + '</span>';
      var cls = 'nav-item' + (it.num === PAGE ? ' active' : '');
      html += it.href
        ? '<a class="' + cls + '" href="' + it.href + '">' + inner + '</a>'
        : '<span class="' + cls + '" style="cursor:default">' + inner + '</span>';
    });
    root.innerHTML = html;
  }

  /* ── 目录索引卡墙（#doc-wall 占位，docs.html 主区默认视图） ── */
  function renderWall() {
    var root = document.getElementById('doc-wall');
    if (!root) return;
    var html = '', lastGroup = null, cards = [];
    DOCS_INDEX.forEach(function (it) {
      if (it.group !== lastGroup) { cards.push({ g: it.group, items: [] }); lastGroup = it.group; }
      cards[cards.length - 1].items.push(it);
    });
    cards.forEach(function (c) {
      html += '<div class="card"><div class="card-head"><h3>' + c.g + '</h3><span class="hint">' + c.items.length + ' 篇</span></div>';
      c.items.forEach(function (it) {
        var inner = '<span class="doc-num">' + it.num + '</span><span>' + it.title + '</span><span class="doc-dir-sum">' + it.summary + '</span>';
        html += it.href
          ? '<a class="doc-dir-row" href="' + it.href + '">' + inner + arrowSvg() + '</a>'
          : '<div class="doc-dir-row disabled">' + inner + '</div>';
      });
      html += '</div>';
    });
    root.innerHTML = html;
  }

  /* ── 搜索态树联动：非命中条目 / 空组降透明 ── */
  function dimTree(q) {
    var root = document.getElementById('doc-tree');
    if (!root) return;
    var hits = search(q);
    var hitNums = hits.map(function (it) { return it.num; });
    root.querySelectorAll('.nav-item').forEach(function (el) {
      var num = (el.querySelector('.doc-num') || {}).textContent;
      el.classList.toggle('dim', !!q && hitNums.indexOf(num) < 0);
    });
    root.querySelectorAll('.nav-label').forEach(function (lab) {
      var any = DOCS_INDEX.some(function (it) {
        return it.group === lab.getAttribute('data-group') && hitNums.indexOf(it.num) >= 0;
      });
      lab.classList.toggle('dim', !!q && !any);
    });
  }

  /* ── 搜索 · 主区模式（docs.html：结果替换卡墙 + API 表） ── */
  function hitRow(it, q) {
    return '<a class="doc-hit" href="' + (it.href || 'javascript:void(0)') + '">'
      + '<span class="doc-num">' + it.num + '</span><span>' + hi(it.title, q) + '</span>'
      + '<span class="badge badge-neutral">' + it.group + '</span>'
      + '<span class="doc-hit-sum">' + hi(it.summary, q) + '</span></a>';
  }
  function setupSearchMain(input) {
    var home = document.getElementById('docs-home');
    var results = document.getElementById('doc-results');
    if (!input || !home || !results) return;
    input.addEventListener('input', function () {
      var q = input.value.trim();
      dimTree(q);
      if (!q) { home.style.display = ''; results.innerHTML = ''; return; }
      var hits = search(q);
      results.innerHTML = hits.length
        ? hits.map(function (it) { return hitRow(it, q); }).join('')
        : '<div class="doc-search-empty">未找到「' + q + '」— 试试 run / key / mcp / webhook</div>';
      home.style.display = 'none';
    });
  }

  /* ── 搜索 · 下拉浮层模式（文章页：↑↓ 选择，Enter 跳转，Esc/点击外部关闭） ── */
  function setupSearchPop(input) {
    var wrap = input.closest('.doc-search');
    var pop = document.getElementById('doc-search-pop');
    if (!wrap || !pop) return;
    var act = -1, items = [];
    function close() { pop.classList.remove('open'); act = -1; }
    function paint(q) {
      items = search(q).slice(0, 8);
      pop.innerHTML = items.length
        ? items.map(function (it, i) {
            return '<a class="doc-hit' + (i === act ? ' active' : '') + '" data-i="' + i + '" href="' + it.href + '">'
              + '<span class="doc-num">' + it.num + '</span><span>' + hi(it.title, q) + '</span>'
              + '<span class="badge badge-neutral">' + it.group + '</span></a>';
          }).join('')
        : '<div class="doc-search-empty">未找到「' + q + '」</div>';
      pop.classList.add('open');
    }
    input.addEventListener('input', function () { act = -1; if (input.value.trim()) paint(input.value.trim()); else close(); });
    input.addEventListener('keydown', function (e) {
      var q = input.value.trim();
      if (e.key === 'Escape') { close(); input.blur(); return; }
      if (!q || !items.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        act = e.key === 'ArrowDown' ? Math.min(act + 1, items.length - 1) : Math.max(act - 1, 0);
        pop.querySelectorAll('.doc-hit').forEach(function (el, i) { el.classList.toggle('active', i === act); });
      } else if (e.key === 'Enter' && act >= 0 && items[act].href) {
        location.href = items[act].href;
      }
    });
    pop.addEventListener('mousedown', function (e) {
      var a = e.target.closest('.doc-hit');
      if (a && a.getAttribute('href')) { e.preventDefault(); location.href = a.getAttribute('href'); }
    });
    document.addEventListener('click', function (e) { if (!e.target.closest('.doc-search')) close(); });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
  }

  /* ── 文章右栏大纲（#doc-outline 占位；scroll 法取视口上方最后一个 h2） ── */
  function renderOutline() {
    var art = document.getElementById('doc-article');
    var out = document.getElementById('doc-outline');
    if (!art || !out) return;
    var hs = [].slice.call(art.querySelectorAll('h2[id]'));
    if (!hs.length) return;
    out.innerHTML = hs.map(function (h) {
      return '<a class="doc-toc-link" href="#' + h.id + '">' + h.textContent + '</a>';
    }).join('');
    var links = [].slice.call(out.querySelectorAll('.doc-toc-link'));
    function update() {
      var cur = 0;
      hs.forEach(function (h, i) { if (h.getBoundingClientRect().top <= 96) cur = i; });
      links.forEach(function (a, i) { a.classList.toggle('active', i === cur); });
    }
    window.addEventListener('scroll', update, { passive: true });
    update();
  }

  /* ── 复制按钮（data-copy="命令全文"；file:// 下 clipboard 可能不可用，静默降级） ── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-copy]');
    if (!btn) return;
    var prev = btn.textContent;
    function done(ok) {
      btn.textContent = ok ? '已复制 ✓' : '复制';
      setTimeout(function () { btn.textContent = prev; }, 1200);
    }
    try {
      navigator.clipboard.writeText(btn.getAttribute('data-copy')).then(function () { done(true); }, function () { done(false); });
    } catch (err) { done(false); }
  });

  /* ── ⌘K / Ctrl+K 聚焦搜索框 ── */
  document.addEventListener('keydown', function (e) {
    if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
      var input = document.getElementById('doc-search');
      if (input) { e.preventDefault(); input.focus(); input.select(); }
    }
  });

  /* ── 启动 ── */
  function init() {
    renderTree();
    renderWall();
    renderOutline();
    var input = document.getElementById('doc-search');
    if (input) {
      setupSearchMain(input);
      setupSearchPop(input);
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();

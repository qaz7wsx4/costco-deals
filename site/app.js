'use strict';

// ---------- 個人資料（只存在這個瀏覽器） ----------
const STORE_KEY = 'costco-deals:v1';
const PREF_KEY = 'costco-deals:prefs';

function load(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch { return fallback; }
}
function save(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* 無痕模式等情況存不了，就只在這次有效 */ }
}

const me = Object.assign({ stars: [], keywords: [], store: {} }, load(STORE_KEY, {}));
const prefs = Object.assign({ src: 'all', sort: 'off', group: '' }, load(PREF_KEY, {}));
const saveMe = () => save(STORE_KEY, me);
const savePrefs = () => save(PREF_KEY, prefs);

// ---------- 工具 ----------
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = (n) => '$' + Math.round(n).toLocaleString('en-US');
const norm = (s) => String(s ?? '').toLowerCase().replace(/\s+/g, '');
const md = (d) => d ? `${+d.slice(5, 7)}/${+d.slice(8, 10)}` : '';
const ym = (d) => d ? `${d.slice(0, 4)}/${d.slice(5, 7)}` : '';
const todayTPE = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Taipei' }).format(new Date());
const dayDiff = (a, b) => Math.round((Date.parse(a) - Date.parse(b)) / 86400000);

function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 1800);
}

// ---------- 資料 ----------
let items = [], hist = {}, updated = '', today = todayTPE();
const byCode = new Map();

async function init() {
  try {
    const [l, h] = await Promise.all([
      fetch('data/latest.json', { cache: 'no-cache' }).then((r) => r.json()),
      fetch('data/history.json', { cache: 'no-cache' }).then((r) => r.json()).catch(() => ({})),
    ]);
    items = l.items; hist = h; updated = l.updated;
  } catch (e) {
    $('#summary').textContent = '資料載入失敗，請稍後重新整理。';
    return;
  }
  items.forEach((it) => { it.eff = effective(it); byCode.set(it.code, it); });
  renderSummary();
  renderGroups();
  bindUI();
  route();
}

// 卡片上主要顯示的價格：有優惠券上的賣場售價就用賣場價，否則用線上價
function effective(it) {
  const s = it.store || {};
  if (s.price) {
    const base = s.base || null, off = s.off || (s.special ? null : it.off);
    return { where: 'store', price: s.price, base, off, pct: base && off ? Math.round(off / base * 100) : null, unit: s.unit };
  }
  if (it.price != null) return { where: 'online', price: it.price, base: it.base, off: it.off, pct: it.pct };
  return { where: 'none', price: null, base: null, off: null, pct: null };
}

function renderSummary() {
  const wallet = items.filter((i) => i.src.includes('wallet')).length;
  const storePriced = items.filter((i) => i.eff.where === 'store').length;
  const endingToday = items.filter((i) => i.end === today).length;
  const upd = updated ? `${md(updated.slice(0, 10))} ${updated.slice(11, 16)} 更新` : '';
  $('#summary').textContent =
    `${items.length} 項特價・會員護照 ${wallet} 項（${storePriced} 項有賣場價）` +
    (endingToday ? `・${endingToday} 項今天結束` : '') + `・${upd}`;
}

// 同一檔特價以外，最近一次的特價
function lastDeal(code, current) {
  const deals = (hist[code]?.deals || []).filter((d) =>
    !current || d.start !== current.start || d.end !== current.end || d.off !== current.off);
  return deals.sort((a, b) => (b.end || '').localeCompare(a.end || ''))[0];
}

function storeEstimate(it) {
  const rec = me.store[it.code];
  if (it.eff.where === 'store' || !rec || !(rec.price > it.off)) return null;
  return { price: rec.price - it.off, rec };
}

// ---------- 商品卡 ----------
function priceBlock(it) {
  const e = it.eff;
  const per = e.unit ? `<span class="per">/${esc(e.unit)}</span>` : '';
  const offText = e.off ? `<span class="off">折 ${money(e.off)}${e.pct ? `（${e.pct}%）` : ''}</span>` : '';
  if (e.where === 'store') {
    const diff = it.online ? it.price - e.price : null;
    return `
      <div class="prices">
        <span class="tag store">賣場</span><span class="now">${money(e.price)}${per}</span>
        ${e.base ? `<span class="was">${money(e.base)}</span>` : ''}${offText}
        ${it.store.special ? '<span class="off">專案活動售價</span>' : ''}
      </div>
      ${it.online ? `<div class="online">線上 ${money(it.price)}（含運${diff > 0 ? `，比賣場多 ${money(diff)}` : diff === 0 ? '，與賣場同價' : ''}）</div>` : ''}`;
  }
  if (e.where === 'online') {
    return `
      <div class="prices">
        <span class="tag">線上</span><span class="now">${money(e.price)}</span>
        <span class="was">${money(e.base)}</span>${offText}
      </div>
      ${it.store ? '<div class="online">賣場價請看優惠券</div>' : ''}`;
  }
  return '<div class="prices"><span class="now muted">價格請看優惠券</span></div>';
}

function unitLine(it) {
  if (!it.unit) return '';
  // 每單位價格是線上的；改用賣場價時等比例換算（同一個包裝）
  const p = it.eff.where === 'store' && it.price ? it.unit.price * it.eff.price / it.price : it.unit.price;
  return `<div class="unit">每${esc(it.unit.per || '單位')} $${p.toLocaleString('en-US', { maximumFractionDigits: 2 })}</div>`;
}

function card(it, extraBadges = '') {
  const left = dayDiff(it.end, today);
  const endBadge =
    left <= 0 ? '<span class="b urgent">今天最後一天</span>' :
    left === 1 ? '<span class="b urgent">明天結束</span>' :
    `<span class="b">到 ${md(it.end)}</span>`;
  const isNew = it.start && dayDiff(today, it.start) <= 3;
  const wallet = it.src.includes('wallet');
  const starred = me.stars.includes(it.code);
  const est = storeEstimate(it);
  const past = lastDeal(it.code, { start: it.start, end: it.end, off: it.off || it.store?.off });
  const coupon = it.store?.coupon;
  const showCoupon = coupon && it.eff.where === 'none';  // 讀不出價格時直接攤開優惠券

  return `
  <article class="card" data-code="${esc(it.code)}">
    <a href="${esc(it.url)}" target="_blank" rel="noopener"><img class="pic" src="${esc(it.img || coupon)}" alt="" loading="lazy"></a>
    <div class="body">
      <a class="name" href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.name)}</a>
      <button class="code" data-act="copy" title="複製商品編號">#${esc(it.code)}</button>
      ${priceBlock(it)}
      ${unitLine(it)}
      <div class="badges">
        ${!wallet ? '<span class="b">可能僅限線上</span>' : it.walletOnline ? '<span class="b wallet">會員護照・僅限線上</span>'
          : `<span class="b wallet">會員護照${it.online ? '・賣場同步' : ''}</span>`}
        ${it.online ? '' : '<span class="b storeonly">賣場限定</span>'}
        ${endBadge}
        ${isNew ? '<span class="b new">新上架</span>' : ''}
        ${it.limit ? `<span class="b">限購 ${it.limit}</span>` : ''}
        ${it.online && !it.stock ? '<span class="b">線上缺貨</span>' : ''}
        ${extraBadges}
      </div>
      ${est ? `<div class="store">賣場預估 <strong>${money(est.price)}</strong>
        <span class="muted">（${md(est.rec.date)} 記錄原價 ${money(est.rec.price)} − 折 ${money(it.off)}${wallet ? '' : '，此折扣可能僅限線上'}）</span></div>` : ''}
      ${past ? `<div class="past">上次特價：${ym(past.end)} 折 ${money(past.off)}</div>` : ''}
      <div class="acts">
        <button class="act star" data-act="star" aria-pressed="${starred}">${starred ? '★ 已收藏' : '☆ 收藏'}</button>
        ${coupon ? `<button class="act" data-act="coupon" aria-expanded="${!!showCoupon}">${showCoupon ? '收起優惠券' : '看優惠券'}</button>` : ''}
        ${it.eff.where === 'store' ? '' : `<button class="act" data-act="store">${me.store[it.code] ? '修改賣場價' : '記錄賣場價'}</button>`}
      </div>
    </div>
    ${coupon ? `<img class="coupon" src="${esc(coupon)}" alt="${esc(it.name)} 優惠券" loading="lazy"${showCoupon ? '' : ' hidden'}>` : ''}
  </article>`;
}

// 目前沒特價的收藏：用歷史紀錄顯示
function offCard(code) {
  const h = hist[code];
  const past = lastDeal(code);
  const rec = me.store[code];
  return `
  <article class="card" data-code="${esc(code)}">
    ${h?.img ? `<img class="pic" src="${esc(h.img)}" alt="" loading="lazy">` : '<div class="pic"></div>'}
    <div class="body">
      ${h?.url ? `<a class="name" href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.name)}</a>` : `<span class="name">${esc(h?.name || '（名稱未知）')}</span>`}
      <button class="code" data-act="copy">#${esc(code)}</button>
      ${past ? `<div class="past">上次特價：${md(past.start)}～${md(past.end)} 折 ${money(past.off)}（${past.where === 'store' ? '賣場' : '線上'} ${money(past.price)}）</div>` : ''}
      ${rec ? `<div class="past">你記錄的賣場原價：${money(rec.price)}（${md(rec.date)}）</div>` : ''}
      <div class="acts">
        <button class="act star" data-act="star" aria-pressed="true">★ 已收藏</button>
      </div>
    </div>
  </article>`;
}

// ---------- 特價列表 ----------
function renderGroups() {
  const counts = {};
  items.forEach((i) => { counts[i.group] = (counts[i.group] || 0) + 1; });
  const last = (g) => (g === '商業採購' || g === '其他') ? 1 : 0;
  const groups = Object.keys(counts).sort((a, b) => last(a) - last(b) || counts[b] - counts[a]);
  if (prefs.group && !counts[prefs.group]) prefs.group = '';
  $('#groups').innerHTML =
    `<button class="chip" data-g="" aria-pressed="${!prefs.group}">全部<span class="n">${items.length}</span></button>` +
    groups.map((g) => `<button class="chip" data-g="${esc(g)}" aria-pressed="${prefs.group === g}">${esc(g)}<span class="n">${counts[g]}</span></button>`).join('');
}

const offOf = (i) => i.eff.off || 0;
const sorters = {
  off: (a, b) => offOf(b) - offOf(a),
  pct: (a, b) => (b.eff.pct || 0) - (a.eff.pct || 0) || offOf(b) - offOf(a),
  end: (a, b) => a.end.localeCompare(b.end) || offOf(b) - offOf(a),
  new: (a, b) => (b.start || '').localeCompare(a.start || '') || offOf(b) - offOf(a),
  price: (a, b) => (a.eff.price ?? Infinity) - (b.eff.price ?? Infinity),
};

function renderDeals() {
  const q = norm($('#q').value);
  let list = items.filter((i) =>
    (prefs.src === 'all' || (prefs.src === 'wallet' ? i.src.includes('wallet') : !i.src.includes('wallet'))) &&
    (!prefs.group || i.group === prefs.group) &&
    (!q || norm(i.name + i.en + i.code + (i.leaf || '')).includes(q)));
  list.sort(sorters[prefs.sort] || sorters.off);
  $('#resultInfo').textContent = `共 ${list.length} 項`;
  $('#list').innerHTML = list.length ? list.map((i) => card(i)).join('') : '<p class="empty">沒有符合的特價商品</p>';
}

// ---------- 想買清單 ----------
function wishMatches() {
  const kws = me.keywords.map((k) => [k, norm(k)]);
  const on = [];
  for (const it of items) {
    const text = norm(it.name + it.en);
    // 商業採購是整箱整棧板的量，不適合拿關鍵字去配
    const hits = it.group === '商業採購' ? [] : kws.filter(([, n]) => text.includes(n)).map(([k]) => k);
    if (me.stars.includes(it.code) || hits.length) on.push({ it, hits });
  }
  const off = me.stars.filter((c) => !byCode.has(c));
  return { on, off };
}

function renderWishCount() {
  const n = wishMatches().on.length;
  const el = $('#wishCount');
  el.hidden = !n;
  el.textContent = n;
}

function renderWish() {
  $('#kwChips').innerHTML = me.keywords.map((k, i) =>
    `<span class="chip kw">${esc(k)}<button data-kw="${i}" aria-label="移除 ${esc(k)}">×</button></span>`).join('');
  const { on, off } = wishMatches();
  on.sort((a, b) => a.it.end.localeCompare(b.it.end) || b.it.off - a.it.off);
  $('#wishOn').innerHTML = on.length
    ? on.map(({ it, hits }) => card(it, hits.map((h) => `<span class="b kwhit">符合「${esc(h)}」</span>`).join(''))).join('')
    : `<p class="empty">${me.stars.length || me.keywords.length ? '你追蹤的東西目前都沒有特價' : '在特價列表按「☆ 收藏」，或在上面加入關鍵字'}</p>`;
  $('#wishOff').innerHTML = off.length ? off.map(offCard).join('') : '<p class="empty">沒有</p>';
}

// ---------- 我的資料 ----------
function renderMe() {
  const rows = Object.entries(me.store).sort((a, b) => b[1].date.localeCompare(a[1].date));
  $('#storeList').innerHTML = rows.length ? rows.map(([code, r]) => {
    const name = byCode.get(code)?.name || hist[code]?.name || '';
    return `<div class="srow"><span class="nm">#${esc(code)} ${esc(name)}</span>
      <span>${money(r.price)}・${md(r.date)} <button class="del" data-del="${esc(code)}">刪除</button></span></div>`;
  }).join('') : '<p class="hint">還沒有紀錄。</p>';
}

// ---------- 路由與事件 ----------
function route() {
  const tab = ['deals', 'wish', 'me'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'deals';
  document.querySelectorAll('.tab').forEach((s) => { s.hidden = s.id !== 'tab-' + tab; });
  document.querySelectorAll('.tabs a').forEach((a) => a.setAttribute('aria-selected', a.dataset.tab === tab));
  renderWishCount();
  if (tab === 'deals') renderDeals();
  if (tab === 'wish') renderWish();
  if (tab === 'me') renderMe();
}

function rerenderCurrent() {
  route();
}

function bindUI() {
  window.addEventListener('hashchange', route);

  let t;
  $('#q').addEventListener('input', () => { clearTimeout(t); t = setTimeout(renderDeals, 120); });
  $('#sort').value = prefs.sort;
  $('#sort').addEventListener('change', (e) => { prefs.sort = e.target.value; savePrefs(); renderDeals(); });
  document.querySelectorAll('#src button').forEach((b) => b.setAttribute('aria-pressed', b.dataset.v === prefs.src));
  $('#src').addEventListener('click', (e) => {
    const b = e.target.closest('button'); if (!b) return;
    prefs.src = b.dataset.v; savePrefs();
    document.querySelectorAll('#src button').forEach((x) => x.setAttribute('aria-pressed', x === b));
    renderDeals();
  });
  $('#groups').addEventListener('click', (e) => {
    const b = e.target.closest('.chip'); if (!b) return;
    prefs.group = b.dataset.g; savePrefs();
    document.querySelectorAll('#groups .chip').forEach((x) => x.setAttribute('aria-pressed', x === b));
    renderDeals();
  });

  // 商品卡上的按鈕（三個分頁共用）
  document.querySelector('main').addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-act]'); if (!btn) return;
    const cardEl = btn.closest('.card'); const code = cardEl?.dataset.code;
    const act = btn.dataset.act;
    if (act === 'copy') {
      try { await navigator.clipboard.writeText(code); toast(`已複製 ${code}`); } catch { toast(code); }
    } else if (act === 'star') {
      const i = me.stars.indexOf(code);
      i >= 0 ? me.stars.splice(i, 1) : me.stars.push(code);
      saveMe();
      toast(i >= 0 ? '已取消收藏' : '已加入想買清單');
      rerenderCurrent();
    } else if (act === 'coupon') {
      const img = cardEl.querySelector('img.coupon');
      img.hidden = !img.hidden;
      btn.setAttribute('aria-expanded', !img.hidden);
      btn.textContent = img.hidden ? '看優惠券' : '收起優惠券';
    } else if (act === 'store') {
      openStoreForm(cardEl, code);
    } else if (act === 'store-save') {
      const v = parseInt(cardEl.querySelector('.storeform input').value, 10);
      if (!(v > 0)) { toast('請輸入賣場原價'); return; }
      me.store[code] = { price: v, date: today };
      saveMe(); toast('已記錄'); rerenderCurrent();
    } else if (act === 'store-del') {
      delete me.store[code]; saveMe(); toast('已刪除紀錄'); rerenderCurrent();
    }
  });

  $('#kwForm').addEventListener('submit', (e) => {
    e.preventDefault();
    const v = $('#kwInput').value.trim();
    if (v && !me.keywords.includes(v)) { me.keywords.push(v); saveMe(); }
    $('#kwInput').value = '';
    renderWish(); renderWishCount();
  });
  $('#kwChips').addEventListener('click', (e) => {
    const b = e.target.closest('[data-kw]'); if (!b) return;
    me.keywords.splice(+b.dataset.kw, 1); saveMe(); renderWish(); renderWishCount();
  });

  $('#storeList').addEventListener('click', (e) => {
    const b = e.target.closest('[data-del]'); if (!b) return;
    delete me.store[b.dataset.del]; saveMe(); renderMe();
  });
  $('#copyBackup').addEventListener('click', async () => {
    const text = JSON.stringify(me);
    $('#backup').value = text;
    try { await navigator.clipboard.writeText(text); $('#backupMsg').textContent = '已複製，到另一台裝置貼上後按「匯入」。'; }
    catch { $('#backup').select(); $('#backupMsg').textContent = '請手動複製上面的文字。'; }
  });
  $('#importBackup').addEventListener('click', () => {
    try {
      const d = JSON.parse($('#backup').value);
      if (!Array.isArray(d.stars) || !Array.isArray(d.keywords) || typeof d.store !== 'object') throw 0;
      me.stars = [...new Set([...me.stars, ...d.stars])];
      me.keywords = [...new Set([...me.keywords, ...d.keywords])];
      me.store = Object.assign({}, me.store, d.store);
      saveMe(); renderMe(); renderWishCount();
      $('#backupMsg').textContent = '匯入完成（已和這台裝置原本的資料合併）。';
    } catch { $('#backupMsg').textContent = '格式不對，請確認貼上的是完整的備份內容。'; }
  });
}

function openStoreForm(cardEl, code) {
  const acts = cardEl.querySelector('.acts');
  if (cardEl.querySelector('.storeform')) return;
  const rec = me.store[code];
  acts.insertAdjacentHTML('afterend', `
    <div class="storeform">
      <input type="number" inputmode="numeric" min="1" placeholder="賣場原價" value="${rec ? rec.price : ''}" aria-label="賣場原價">
      <button data-act="store-save">儲存</button>
      ${rec ? '<button class="act" data-act="store-del">刪除</button>' : ''}
    </div>`);
  const input = cardEl.querySelector('.storeform input');
  input.focus();
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') cardEl.querySelector('[data-act="store-save"]').click(); });
}

init();

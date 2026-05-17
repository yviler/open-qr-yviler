let cart = [];
let currentPopupItem = null;

/* ---------- i18n strings ---------- */
const STRINGS = {
  SELECT_ONE_DISH: (typeof lang !== 'undefined' && lang === 'en') ? "Please pick one style." : "Silakan pilih satu jenis masakan.",
  NOTE:            (typeof lang !== 'undefined' && lang === 'en') ? "Note:" : "Catatan:",
  REMOVE_ITEM:     (typeof lang !== 'undefined' && lang === 'en') ? "Remove this item from cart?" : "Hapus item ini dari keranjang?",
  ADD_TO_CART:     (typeof lang !== 'undefined' && lang === 'en') ? "Add to Cart" : "Tambah ke Keranjang",
  ADD_ANOTHER:     (typeof lang !== 'undefined' && lang === 'en') ? "Add Another" : "Tambah Lagi",
  QTY_PORTIONS:    (typeof lang !== 'undefined' && lang === 'en') ? "Qty (portions):" : "Jumlah (porsi):",
  PORTION_SIZE:    (typeof lang !== 'undefined' && lang === 'en') ? "Portion size:" : "Ukuran porsi:"
};

/* ---------- small helpers ---------- */
function isUnavailable(el){
  const card = el && el.closest ? el.closest('.item-card') : null;
  return !!(card && card.classList.contains('unavailable'));
}
function parseOns(str){
  const m = String(str || '').match(/(\d+(?:\.\d+)?)\s*ons/i);
  return m ? Math.round(parseFloat(m[1])) : null;
}
function defaultOnsFromInfo(info){
  const m = String(info || '').match(/(\d+)\s*[–-]\s*(\d+)\s*ons/i);
  if (m){
    const lo = parseInt(m[1], 10), hi = parseInt(m[2], 10);
    return Math.round((lo + hi) / 2);
  }
  const s = String(info || '').match(/(\d+(?:\.\d+)?)\s*ons/i);
  return s ? Math.round(parseFloat(s[1])) : 7;
}
function blink(el){
  if (!el) return;
  el.classList.remove('blink');
  void el.offsetWidth;                 // reflow to restart animation
  el.classList.add('blink');
  setTimeout(() => el.classList.remove('blink'), 360);
}

/* ---------- popup ---------- */
function openPopup({ category, posName, displayName, dishOptions, unit, portionInfo, portionChoices }) {
  currentPopupItem = {
    category,
    posName,
    displayName,
    dishOptions,
    unit: (unit || '').toLowerCase(),
    portionInfo,
    portionChoices
  };

  // title + image
  const titleEl = document.getElementById('popup-item-name');
  if (titleEl) titleEl.textContent = displayName || posName;
  const picEl = document.getElementById('popup-pic');
  if (picEl){
    if (window.__lastPopupBtn?.dataset.pic) {
      picEl.src = window.__lastPopupBtn.dataset.pic;
      picEl.alt = displayName || posName;
    } else {
      picEl.removeAttribute('src');
      picEl.removeAttribute('alt');
    }
  }

  // dish radios (single-select)
  const saucesDiv = document.getElementById('sauce-options');
  if (saucesDiv){
    saucesDiv.innerHTML = '';
    if (dishOptions.length){
      saucesDiv.style.display = 'block';
      dishOptions.forEach((dish, i) => {
        const id = `dish_${i}`;
        const el = document.createElement('div');
        el.className = 'sauce-option';
        el.innerHTML = `
          <input type="radio" id="${id}" name="dish" value="${dish}">
          <label for="${id}">${dish}</label>`;
        saucesDiv.appendChild(el);
      });
    } else {
      saucesDiv.style.display = 'none';
    }
  }

  // qty stepper (popup)
  const qtyInput = document.getElementById('qty-input');
  const qtyDisplay = document.getElementById('qty-display');
  if (qtyInput && qtyDisplay){
    qtyInput.min = 1; qtyInput.step = 1; qtyInput.value = 1; qtyDisplay.textContent = '1';
    const dec = document.getElementById('qty-minus');
    const inc = document.getElementById('qty-plus');
    if (dec) dec.onclick = () => {
      const v = Math.max(1, (parseInt(qtyInput.value || '1', 10) - 1));
      qtyInput.value = v; qtyDisplay.textContent = String(v);
      if (window.__lastPopupBtn) window.__onOpenPopup?.(window.__lastPopupBtn);
      blink(qtyDisplay);
    };
    if (inc) inc.onclick = () => {
      const v = (parseInt(qtyInput.value || '1', 10) + 1);
      qtyInput.value = v; qtyDisplay.textContent = String(v);
      if (window.__lastPopupBtn) window.__onOpenPopup?.(window.__lastPopupBtn);
      blink(qtyDisplay);
    };
  }

  // portion size selector (for ons)
  let sizeRow = document.getElementById('portion-size-row');
  if (!sizeRow){
    sizeRow = document.createElement('div');
    sizeRow.id = 'portion-size-row';
    const noteEl = document.getElementById('note-input');
    const anchor = noteEl ? noteEl.parentNode : null;
    if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(sizeRow, anchor);
    else (document.querySelector('.popup-content') || document.body).appendChild(sizeRow);
  }
  sizeRow.innerHTML = '';

  if (currentPopupItem.unit === 'ons'){
    const pChoices = currentPopupItem.portionChoices || [];
    if (Array.isArray(pChoices) && pChoices.length){
      const label = document.createElement('label');
      label.textContent = STRINGS.PORTION_SIZE + ' ';
      const sel = document.createElement('select');
      sel.id = 'portion-size';
      pChoices.forEach(choice => {
        const ons = parseOns(choice);
        if (!ons) return;
        const opt = document.createElement('option');
        opt.value = String(ons);
        opt.textContent = `${ons * 100} g / porsi`;
        sel.appendChild(opt);
      });
      label.appendChild(sel);
      sizeRow.appendChild(label);
    } else {
      sizeRow.innerHTML = `<small style="opacity:.8">${currentPopupItem.portionInfo || ''}</small>`;
    }
  } else {
    sizeRow.innerHTML = '';
    const est = document.getElementById('est-label');
    if (est) est.textContent = '';
  }

  const noteIn = document.getElementById('note-input');
  if (noteIn) noteIn.value = '';

  const popup = document.getElementById('popup');
  if (popup) popup.style.display = 'flex';

  // initial estimator refresh
  if (window.__lastPopupBtn) window.__onOpenPopup?.(window.__lastPopupBtn);
}
function closePopup(){ const p = document.getElementById('popup'); if (p) p.style.display = 'none'; }

/* ---------- add to cart (from popup) ---------- */
function addPopupToCart(){
  const note = document.getElementById('note-input')?.value || '';
  const portionQty = Math.max(1, parseInt(document.getElementById('qty-input')?.value || '1', 10));

  // dish selection
  let dish = null;
  if (currentPopupItem.dishOptions.length){
    const sel = document.querySelector('input[name="dish"]:checked');
    if (!sel){ alert(STRINGS.SELECT_ONE_DISH); return; }
    dish = sel.value;
  }

  const basePos = currentPopupItem.posName;
  const posName = dish ? `${basePos} - ${dish}` : basePos;
  const displayName = dish || currentPopupItem.displayName || basePos;

  let unitSend = currentPopupItem.unit || 'portion';
  let onsPerPortion = 1;
  if (unitSend === 'ons'){
    const sel = document.getElementById('portion-size');
    onsPerPortion = sel && sel.value ? (parseInt(sel.value, 10) || 1) : defaultOnsFromInfo(currentPopupItem.portionInfo);
  }
  const qtySend = (unitSend === 'ons') ? (portionQty * onsPerPortion) : portionQty;

  const existing = cart.find(x =>
    x.item === posName &&
    x.note === note &&
    (x.opp || 1) === onsPerPortion &&
    (x.unit || 'portion') === unitSend
  );

  const btn = window.__lastPopupBtn;
  const pricePerOns = Number(btn?.dataset.pricePerOns || 0);

  // robust unit price for non-ons
  let unitPrice = Number(btn?.dataset.unitPrice || btn?.dataset.unitprice || 0);
  if (!unitPrice && unitSend !== 'ons'){
    const priceEl = btn?.closest('.item-card')?.querySelector('.price');
    if (priceEl){
      const num = (priceEl.textContent || '').replace(/[^\d]/g, '');
      unitPrice = Number(num || 0);
    }
  }

  if (existing){
    existing.portion_qty += portionQty;
    existing.qty = (existing.unit === 'ons')
      ? existing.portion_qty * (existing.opp || 1)
      : existing.portion_qty;
  } else {
    cart.push({
      item: posName,
      disp: displayName,
      unit: unitSend,                // 'portion' or 'ons'
      opp: onsPerPortion,            // ons per portion (for 'ons')
      portion_qty: portionQty,       // number of portions in this line
      qty: qtySend,                  // actual 'ons' or portion count
      note,
      price_per_ons: (unitSend === 'ons' ? pricePerOns : null),
      unit_price: (unitSend !== 'ons' ? unitPrice : null)
    });
  }

  updateCartDisplay();
  updateAddToCartButtons();
  closePopup();
}

/* ---------- simple in-page list (if present) & persistence ---------- */
function updateCartDisplay(){
  const cartDiv = document.getElementById('cart');
  if (cartDiv){
    cartDiv.innerHTML = '';
    cart.forEach((it, idx) => {
      const humanQty = (String(it.unit || '').toLowerCase() === 'ons')
        ? `${it.portion_qty} porsi`
        : `${it.qty} ${(typeof lang !== 'undefined' && lang === 'en') ? 'portion' : 'porsi'}`;
      const div = document.createElement('div');
      div.className = 'cart-item';
      div.innerHTML = `
        <strong>${it.disp}</strong> × ${humanQty}<br>
        ${STRINGS.NOTE} ${it.note || '-'}<br>
        <button onclick="increaseQty(${idx})">+</button>
        <button onclick="decreaseQty(${idx})">−</button>
        <hr>`;
      cartDiv.appendChild(div);
    });
  }

  // hidden payload for /cart page
  const cartDataInput = document.getElementById('cart_data');
  if (cartDataInput) cartDataInput.value = JSON.stringify(cart);

  // badge on header button
  const cartCountEl = document.getElementById('cart-count');
  if (cartCountEl){
    const total = cart.reduce((a, x) => a + (String(x.unit || '').toLowerCase() === 'ons' ? (x.portion_qty || 0) : (x.qty || 0)), 0);
    cartCountEl.textContent = total;
  }

  try { sessionStorage.setItem('cart', JSON.stringify(cart)); } catch(_) {}
}
function increaseQty(i){
  const it = cart[i];
  if (!it) return;
  if (String(it.unit || '').toLowerCase() === 'ons'){
    it.portion_qty += 1;
    it.qty = it.portion_qty * (it.opp || 1);
  } else {
    it.qty += 1;
  }
  updateCartDisplay();
  updateAddToCartButtons();
}
function decreaseQty(i){
  const it = cart[i];
  if (!it) return;
  if (String(it.unit || '').toLowerCase() === 'ons'){
    if ((it.portion_qty || 1) > 1){
      it.portion_qty -= 1;
      it.qty = it.portion_qty * (it.opp || 1);
    } else if (confirm(STRINGS.REMOVE_ITEM)){
      cart.splice(i, 1);
    }
  } else {
    if ((it.qty || 1) > 1) it.qty -= 1;
    else if (confirm(STRINGS.REMOVE_ITEM)) cart.splice(i, 1);
  }
  updateCartDisplay();
  updateAddToCartButtons();
}

/* ---------- add button -> open popup (for all) ---------- */
function handleAddToCart(btn){
  if (isUnavailable(btn)) return;
  window.__lastPopupBtn = btn;
  const posName = (btn.dataset.item || '').trim();
  const displayName = (btn.dataset.displayName || posName).trim();
  const category = btn.dataset.category;

  // sauces / sub-dishes
  let dishOptions = [];
  try { dishOptions = JSON.parse(btn.dataset.sauces || '[]'); } catch {}
  const normalized = dishOptions
    .map(s => typeof s === 'string' ? s : (s && s.name) || '')
    .filter(Boolean);

  // ons portion choices
  let portionChoices = [];
  try { portionChoices = JSON.parse(btn.dataset.portionChoices || '[]'); } catch {}

  openPopup({
    category,
    posName,
    displayName,
    dishOptions: normalized,
    unit: btn.dataset.unit || '',
    portionInfo: btn.dataset.portionInfo || '',
    portionChoices
  });
}

/* ---------- stepper logic (ALL items) ---------- */
function totalPortionsForItem(itemName){
  let sum = 0;
  cart.forEach(x => {
    if (x.item === itemName){
      const isOns = String(x.unit || '').toLowerCase() === 'ons';
      sum += isOns ? (x.portion_qty || 0) : (x.qty || 0);
    }
  });
  return sum;
}
function removeOnePortionForOns(itemName){
  // remove/decrement the last matching ons line
  for (let i = cart.length - 1; i >= 0; i--){
    const it = cart[i];
    if (it.item === itemName && String(it.unit || '').toLowerCase() === 'ons'){
      if ((it.portion_qty || 1) > 1){
        it.portion_qty -= 1;
        it.qty = (it.portion_qty || 1) * (it.opp || 1);
      } else {
        cart.splice(i, 1);
      }
      return;
    }
  }
}
function bootstrapInlineSteppers(){
  document.querySelectorAll('.add-to-cart-btn').forEach(btn => {
    if (isUnavailable(btn)){
      btn.disabled = true;
      btn.setAttribute('aria-disabled', 'true');
      return;
    }
    if (!btn.nextElementSibling || !btn.nextElementSibling.classList.contains('inline-stepper')){
      const st = document.createElement('div');
      st.className = 'inline-stepper';
      st.innerHTML = `
        <button type="button" data-act="dec" aria-label="Kurangi">−</button>
        <span class="qty">0</span>
        <button type="button" data-act="inc" aria-label="Tambah">+</button>`;
      btn.insertAdjacentElement('afterend', st);

      // wire +/- (works for portion & ons)
      st.addEventListener('click', (e) => {
        const act = e.target?.dataset?.act;
        if (!act) return;

        const itemName = (btn.dataset.item || '').trim();
        const unit = (btn.dataset.unit || '').toLowerCase();

        if (unit === 'ons'){
          if (act === 'inc'){
            // open popup to choose grams/portion size
            handleAddToCart(btn);
          } else if (act === 'dec'){
            removeOnePortionForOns(itemName);
            updateCartDisplay();
            updateAddToCartButtons();
          }
          const q = st.querySelector('.qty');
          if (q) q.textContent = totalPortionsForItem(itemName);
          return;
        }

        // portion items
        const idx = cart.findIndex(x => x.item === itemName && (x.unit || 'portion') !== 'ons');
        if (act === 'inc'){
          if (idx === -1){
            // create new line via popup (keeps note support)
            handleAddToCart(btn);
          } else {
            cart[idx].qty += 1;
            updateCartDisplay();
            updateAddToCartButtons();
            blink(st.querySelector('.qty'));
          }
        } else if (act === 'dec'){
          if (idx === -1) return;
          if ((cart[idx].qty || 1) > 1) cart[idx].qty -= 1;
          else cart.splice(idx, 1);
          updateCartDisplay();
          updateAddToCartButtons();
          blink(st.querySelector('.qty'));
        }
      });
    }
  });
}
function updateAddToCartButtons(){
  bootstrapInlineSteppers();

  document.querySelectorAll('.add-to-cart-btn').forEach(btn => {
    if (isUnavailable(btn)){
      btn.disabled = true;
      btn.setAttribute('aria-disabled', 'true');
      const st = (btn.nextElementSibling && btn.nextElementSibling.classList.contains('inline-stepper'))
        ? btn.nextElementSibling
        : null;
      if (st) st.style.display = 'none';
      btn.style.display = '';
      return;
    }
    const itemName = (btn.dataset.item || '').trim();
    const stepper = btn.nextElementSibling?.classList.contains('inline-stepper')
      ? btn.nextElementSibling : null;
    const qty = totalPortionsForItem(itemName);

    // show stepper when qty > 0, hide button; else inverse
    if (stepper){
      stepper.style.display = (qty > 0) ? 'flex' : 'none';
      const q = stepper.querySelector('.qty');
      if (q) q.textContent = qty;
    }
    btn.style.display = (qty > 0) ? 'none' : '';
  });
}

/* ---------- clicking a card opens popup (nice for images) ---------- */
function wireCardOpeners(){
  document.querySelectorAll('.item-card').forEach(card => {
    card.addEventListener('click', (e) => {
      if (card.classList.contains('unavailable')) return;
      // ignore clicks on the actual controls
      if (e.target.closest('.btn-add') || e.target.closest('.inline-stepper')) return;
      const btn = card.querySelector('.btn-add');
      if (btn) handleAddToCart(btn);
    });
  });
}

/* ---------- chips + category quick sheet ---------- */
function buildChipSubcategories(){
  document.querySelectorAll('section.menu-section').forEach(sec => {
    const secId = '#' + sec.id;
    const chip = Array.from(document.querySelectorAll('.chip')).find(c => c.dataset.cat === secId);
    if (!chip) return;
    const subs = Array.from(sec.querySelectorAll('h3.subcat-title')).map(h => ({
      name: h.textContent.trim(),
      anchor: '#' + h.id
    }));
    if (subs.length) chip.dataset.subcats = JSON.stringify(subs);
    else delete chip.dataset.subcats;
  });
}
function wireChips(){
  // one overlay
  let sheetRoot = document.getElementById('subcatSheetRoot');
  if (!sheetRoot){
    const wrapper = document.createElement('div');
    wrapper.id = 'subcatSheetRoot';
    wrapper.innerHTML = `
      <div style="position:fixed;inset:0;background:rgba(0,0,0,.3);display:none;align-items:flex-end;z-index:6000">
        <div id="sheetPanel" style="background:#fff;border-radius:16px 16px 0 0;padding:12px;max-height:60vh;overflow:auto;width:100%">
          <div style="height:4px;width:42px;background:#e5e7eb;border-radius:99px;margin:6px auto 12px"></div>
          <div id="sheetTitle" style="font-weight:700;padding:0 8px 8px"></div>
          <div id="sheetList" style="display:grid;grid-template-columns:repeat(2,1fr);gap:8px;padding:0 8px 12px"></div>
        </div>
      </div>`;
    document.body.appendChild(wrapper);
    sheetRoot = wrapper.firstElementChild;
  }
  const panel  = sheetRoot.querySelector('#sheetPanel');
  const title  = sheetRoot.querySelector('#sheetTitle');
  const list   = sheetRoot.querySelector('#sheetList');

  sheetRoot.addEventListener('click', (e) => {
    if (e.target === sheetRoot) sheetRoot.style.display = 'none';
  });

  function openSheet(t, entries){
    if (!panel || !title || !list) return;
    title.textContent = t;
    list.innerHTML = '';
    entries.forEach(({ name, anchor }) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = name;
      btn.style.cssText = 'border:1px solid #e5e7eb;border-radius:10px;padding:10px;background:#fff;text-align:left';
      btn.addEventListener('click', () => {
        sheetRoot.style.display = 'none';
        const tgt = document.querySelector(anchor);
        if (tgt) scrollWithOffset(tgt);
      });
      list.appendChild(btn);
    });
    sheetRoot.style.display = 'flex';
  }

  // All-category sheet (three-line button)
  const allCategories = Array.from(document.querySelectorAll('#catChips a.chip'))
    .map(ch => ({ name: ch.textContent.trim(), anchor: ch.dataset.cat }))
    .filter(x => x.name && x.anchor);
  const catBtn = document.getElementById('btn-cats');
  if (catBtn){
    catBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (allCategories.length){
        openSheet(catBtn.getAttribute('aria-label') || catBtn.textContent.trim() || 'Categories', allCategories);
      }
    });
  }

  document.querySelectorAll('.chip').forEach(ch => {
    if (ch.id === 'btn-cats') return;
    ch.addEventListener('click', (e) => {
      const subs = ch.dataset.subcats ? JSON.parse(ch.dataset.subcats) : null;
      if (subs && subs.length){
        e.preventDefault();
        openSheet(ch.textContent.trim(), subs);
        return;
      }
      const target = document.querySelector(ch.dataset.cat);
      if (target){ e.preventDefault(); scrollWithOffset(target); }
    });
  });
}

/* ---------- sticky offsets & smooth anchor ---------- */
function setStickyOffsets(){
  const hdrH    = document.getElementById('hdr')?.offsetHeight || 0;
  const chipsH  = document.getElementById('catChips')?.offsetHeight || 0;
  const topbarH = document.querySelector('.topbar')?.offsetHeight || 0;
  document.documentElement.style.setProperty('--hdrH', hdrH + 'px');
  document.documentElement.style.setProperty('--chipsH', chipsH + 'px');
  document.documentElement.style.setProperty('--topbarH', topbarH + 'px');
}
function scrollWithOffset(target){
  const cs = getComputedStyle(document.documentElement);
  const hdrH    = parseInt(cs.getPropertyValue('--hdrH'))   || 0;
  const chipsH  = parseInt(cs.getPropertyValue('--chipsH')) || 0;
  const topbarH = parseInt(cs.getPropertyValue('--topbarH'))|| 0;
  const y = target.getBoundingClientRect().top + window.scrollY - (hdrH + chipsH + topbarH + 8);
  window.scrollTo({ top: y, behavior: 'smooth' });
}
window.addEventListener('resize', setStickyOffsets);
window.addEventListener('scroll', () => {
  const hdrH = document.getElementById('hdr')?.offsetHeight || 0;
  document.documentElement.style.setProperty('--hdrH', hdrH + 'px');
});

/* ---------- estimator hook (GRAMS) ---------- */
window.__onOpenPopup = function(btn){
  const perOns = Number(btn.dataset.pricePerOns || 0);   // price per 100 g
  const mn     = Number(btn.dataset.portionMinOns || 0); // in 'ons'
  const mx     = Number(btn.dataset.portionMaxOns || 0); // in 'ons'
  const qty    = Number(document.getElementById('qty-input')?.value || 1);
  const est    = document.getElementById('est-label');
  if (!est) return;

  if (mn > 0){
    const gMin = mn * 100 * qty;
    const gMax = (mx || mn) * 100 * qty;

    const weightTxt = (mx && mx !== mn)
      ? `${gMin.toLocaleString()}–${gMax.toLocaleString()} g`
      : `${gMin.toLocaleString()} g`;

    if (perOns > 0){
      const low  = perOns * mn * qty;
      const high = perOns * (mx || mn) * qty;
      const priceTxt = (mx && mx !== mn)
        ? `Rp${low.toLocaleString()}–Rp${high.toLocaleString()}`
        : `Rp${low.toLocaleString()}`;
      est.textContent = (typeof lang !== 'undefined' && lang === 'en')
        ? `Estimated weight: ${weightTxt} • Estimated total: ${priceTxt}`
        : `Perkiraan berat: ${weightTxt} • Estimasi total: ${priceTxt}`;
    } else {
      est.textContent = (typeof lang !== 'undefined' && lang === 'en')
        ? `Estimated weight: ${weightTxt}`
        : `Perkiraan berat: ${weightTxt}`;
    }
  } else {
    est.textContent = '';
  }
};
// Update estimate when qty changes inside popup
document.getElementById('qty-input')?.addEventListener('input', () => {
  if (window.__lastPopupBtn) window.__onOpenPopup(window.__lastPopupBtn);
});

/* ---------- cart badge poller (server) ---------- */
const CART_POLL_MS = Number(window.__cartPollMs || 8000);
let cartPollTimer = null;

async function refreshCartCount(){
  try{
    const r = await fetch(`/qr/session_summary.json?session=${encodeURIComponent(sessionId)}`, { cache: 'no-store' });
    if (!r.ok) return;
    const data = await r.json();
    const count = Number(data.open_items_count || data.cart_count || 0);
    const el = document.getElementById('cart-count');
    if (el) el.textContent = count;
  } catch(_) {}
}
function startCartPoll(){
  if (cartPollTimer) return;
  refreshCartCount();
  cartPollTimer = setInterval(refreshCartCount, CART_POLL_MS);
}
function stopCartPoll(){
  if (!cartPollTimer) return;
  clearInterval(cartPollTimer);
  cartPollTimer = null;
}

/* ---------- boot ---------- */
document.addEventListener('DOMContentLoaded', () => {
  // restore cart
  const saved = sessionStorage.getItem('cart');
  if (saved){ try { cart = JSON.parse(saved); } catch(_) { cart = []; } }
  updateCartDisplay();

  // stepper + buttons
  bootstrapInlineSteppers();
  updateAddToCartButtons();

  // card click opens popup
  wireCardOpeners();

  // chips sheet & offsets
  buildChipSubcategories();
  wireChips();
  setStickyOffsets();

  // popup backdrop close
  const popup = document.getElementById('popup');
  if (popup){
    popup.addEventListener('click', (e) => { if (e.target === e.currentTarget) closePopup(); });
  }

  // cart count poller
  try { startCartPoll(); } catch(_){}
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopCartPoll();
    else startCartPoll();
  });
});
window.addEventListener('storage', () => {
  const saved = sessionStorage.getItem('cart');
  if (saved){ try { cart = JSON.parse(saved); } catch(_) { cart = []; } updateCartDisplay(); updateAddToCartButtons(); }
});

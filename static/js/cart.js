function formatIDR(n){ return 'Rp' + (Math.round(n||0)).toLocaleString('id-ID'); }

function validateBeforeSubmit() {
  const cart = JSON.parse(sessionStorage.getItem("cart") || "[]");
  if (cart.length === 0) {
    alert(lang === "en" ? "Your cart is empty" : "Keranjang anda kosong");
    return false;
  }
  return confirm(
    lang === "en"
      ? "Are you sure? Once submitted, the order cannot be modified or changed"
      : "Apakah anda yakin? Setelah dikirim, pesanan tidak bisa diubah atau dibatalkan"
  );
}

function lineTotal(it){
  // ON WEIGHT (ons): need price_per_ons and total ons in it.qty
  if ((it.unit||'').toLowerCase() === 'ons'){
    const ppo = Number(it.price_per_ons || 0);
    const ons = Number(it.qty || 0);     // qty is total ons (portions * opp)
    return ppo > 0 ? ppo * ons : 0;
  }
  // PER-ITEM / PORTION
  const up = Number(it.unit_price || 0);
  const q  = Number(it.qty || it.portion_qty || 0);
  return up > 0 ? up * q : 0;
}

function humanQty(it){
  if ((it.unit||'').toLowerCase() === 'ons'){
    const portions = Number(it.portion_qty || Math.max(1, Math.floor((it.qty||1) / Math.max(1,(it.opp||1)))));
    return (lang==='en' ? `${portions} portion(s)` : `${portions} porsi`);
  }
  return (lang==='en' ? `${it.qty||1} portion(s)` : `${it.qty||1} porsi`);
}

function updateTotals(cart){
  let subtotal = 0;
  cart.forEach(it => subtotal += lineTotal(it));
  const tax = subtotal * 0.10;
  const service = subtotal * 0.05;
  const total = subtotal + tax + service;

  const $ = s=>document.querySelector(s);
  $("#subtot").textContent   = formatIDR(subtotal);
  $("#taxval").textContent   = formatIDR(tax);
  $("#serviceval").textContent = formatIDR(service);
  $("#totalval").textContent = formatIDR(total);
}

function updateCartDisplay(){
  const cart = JSON.parse(sessionStorage.getItem("cart") || "[]");
  const cartDiv = document.getElementById("cart");
  const cartDataInput = document.getElementById("cart_data");

  cartDiv.innerHTML = "";

  if (cart.length === 0) {
    cartDiv.innerHTML = `<p class="cart-empty">${ lang === "en" ? "Cart is empty." : "Keranjang kosong." }</p>`;
  } else {
    cart.forEach((it, index) => {
      const name = (it.disp || it.item || '').trim();
      const note = (it.note || '').trim();
      const price = lineTotal({ ...it, qty: (it.unit==='ons' ? (it.opp||1) : 1) }); // price per single step
      const priceLabel = (it.unit||'').toLowerCase()==='ons'
        ? formatIDR(price * (it.portion_qty||1))
        : formatIDR(price * (it.qty||1));

      // Row
      const row = document.createElement('div');
      row.className = 'cart-row';
      row.innerHTML = `
        <div class="item-main">
          <div class="item-title">${name}</div>
          ${ note ? `<div class="item-note">${lang==='en'?'Note':'Catatan'}: ${note}</div>` : '' }
        </div>

        <div class="qty-stepper" role="group" aria-label="${lang==='en'?'Change quantity':'Ubah jumlah'}">
          <button type="button" class="qty-btn" data-act="dec" aria-label="${lang==='en'?'Decrease':'Kurangi'}">−</button>
          <span class="qty-amt">${ (it.unit==='ons') ? (it.portion_qty||1) : (it.qty||1) }</span>
          <button type="button" class="qty-btn" data-act="inc" aria-label="${lang==='en'?'Increase':'Tambah'}">+</button>
        </div>

        <div class="line-price">${ formatIDR(lineTotal(it)) }</div>
      `;

      // Hook up +/- for this row
      row.querySelectorAll('.qty-btn').forEach(btn => {
        btn.addEventListener('click', () => {
          if (btn.dataset.act === 'inc') increaseQty(index);
          else decreaseQty(index);
        });
      });

      cartDiv.appendChild(row);
    });
  }

  if (cartDataInput) cartDataInput.value = JSON.stringify(cart);
  updateTotals(cart);
}

function increaseQty(i){
  const cart = JSON.parse(sessionStorage.getItem("cart") || "[]");
  const it = cart[i];
  if (!it) return;

  if ((it.unit||'').toLowerCase() === 'ons'){
    it.portion_qty = (it.portion_qty||1) + 1;
    it.qty = it.portion_qty * (it.opp||1);   // total ons = porsi * ons per porsi
  } else {
    it.qty = (it.qty||1) + 1;
  }
  sessionStorage.setItem("cart", JSON.stringify(cart));
  updateCartDisplay();
}

function decreaseQty(i){
  const cart = JSON.parse(sessionStorage.getItem("cart") || "[]");
  const it = cart[i];
  if (!it) return;

  if ((it.unit||'').toLowerCase() === 'ons'){
    if ((it.portion_qty||1) > 1){
      it.portion_qty -= 1;
      it.qty = it.portion_qty * (it.opp||1);
    } else if (confirm(lang==='en'?"Remove this item from cart?":"Hapus item ini dari keranjang?")){
      cart.splice(i,1);
    }
  } else {
    if ((it.qty||1) > 1){
      it.qty -= 1;
    } else if (confirm(lang==='en'?"Remove this item from cart?":"Hapus item ini dari keranjang?")){
      cart.splice(i,1);
    }
  }
  sessionStorage.setItem("cart", JSON.stringify(cart));
  updateCartDisplay();
}

function _updateStickyPadding(){
  const list = document.querySelector('.cart-list');
  if (!list) return;

  const sb = document.getElementById('submit-btn');
  const cb = document.getElementById('continue-btn');

  // Measure just the action buttons (not the totals)
  let h = 0;
  if (sb) h = Math.max(h, Math.round(sb.getBoundingClientRect().height || 0));
  if (cb) h = Math.max(h, Math.round(cb.getBoundingClientRect().height || 0));

  // Sensible defaults & clamp to a compact bar
  if (!h) h = 39;                     // fallback
  h = Math.max(32, Math.min(h, 48));  // clamp 32–48px

  list.style.setProperty('--stickyH', (h + 8) + 'px'); // tiny breathing room
}

window.addEventListener('load', _updateStickyPadding);
window.addEventListener('resize', _updateStickyPadding);

const _origUpdateCartDisplay = updateCartDisplay;
updateCartDisplay = function(){
  _origUpdateCartDisplay();
  // wait one frame so DOM settles, then measure
  requestAnimationFrame(_updateStickyPadding);
};

try {
  new ResizeObserver(_updateStickyPadding)
    .observe(document.querySelector('.sticky-actions'));
} catch(_) {}


document.addEventListener("DOMContentLoaded", updateCartDisplay);

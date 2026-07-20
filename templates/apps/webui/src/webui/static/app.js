/* KSF Web UI — app.js
   Alpine.js + HTMX
   Store toasts, composants layout/modal/tabs, helpers ksfConfirm/ksfAction,
   événements HTMX et délégation [data-ksf-confirm]. */

document.addEventListener('alpine:init', () => {
  /* === Store : toasts === */
  Alpine.store('toasts', {
    items: [],
    seed: 0,
    _id() { return ++this.seed; },
    _push(type, message, ttl) {
      const id = this._id();
      this.items.push({ id, type, message });
      if (ttl > 0) setTimeout(() => this.dismiss(id), ttl);
    },
    success(m, t = 4000) { this._push('success', m, t); },
    error(m, t = 6000)   { this._push('error', m, t); },
    warning(m, t = 5000) { this._push('warning', m, t); },
    info(m, t = 4000)    { this._push('info', m, t); },
    dismiss(id) { this.items = this.items.filter(t => t.id !== id); },
  });

  /* === ksfLayout : sidebar rail (desktop) / drawer (mobile) === */
  Alpine.data('ksfLayout', () => ({
    sidebarOpen: window.innerWidth > 1023,
    sidebarCollapsed: false,
    isDrawer: window.innerWidth <= 1023,
    init() {
      window.matchMedia('(max-width: 1023px)').addEventListener('change', e => {
        this.isDrawer = e.matches;
        this.sidebarCollapsed = false;
        this.sidebarOpen = !e.matches;
      });
    },
    sidebarToggle() {
      if (this.isDrawer) {
        this.sidebarOpen = !this.sidebarOpen;
        this.$nextTick(() => this.$el.querySelector('.sidebar-brand')?.focus());
      } else {
        this.sidebarCollapsed = !this.sidebarCollapsed;
        this.sidebarOpen = !this.sidebarCollapsed;
      }
    },
    sidebarClose() {
      if (!this.isDrawer || !this.sidebarOpen) return;
      this.sidebarOpen = false;
      this.$nextTick(() => this.$refs.menuButton?.focus());
    },
  }));

  /* === ksfModal : confirmation avec focus trap === */
  Alpine.data('ksfModal', () => ({
    open: false,
    message: '',
    danger: false,
    _resolve: null,
    _opener: null,
    init() {
      window.__ksfModal = { confirm: (msg, danger = false, opener) => {
        this.message = msg;
        this.danger = !!danger;
        this._opener = opener instanceof HTMLElement ? opener : null;
        this.open = true;
        this._resolve?.(false);
        this.$nextTick(() => this.$refs.cancelButton?.focus());
        return new Promise(r => { this._resolve = r; });
      }};
    },
    confirm() { this._resolve?.(true); this.close(); },
    cancel()  { this._resolve?.(false); this.close(); },
    close() {
      this.open = false;
      const opener = this._opener;
      this._opener = null;
      if (opener?.isConnected) this.$nextTick(() => opener.focus());
    },
    trapFocus(event) {
      const items = [...this.$refs.body.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )];
      if (!items.length || event.key !== 'Tab') return;
      if (event.shiftKey && document.activeElement === items[0]) {
        event.preventDefault(); items.at(-1).focus();
      } else if (!event.shiftKey && document.activeElement === items.at(-1)) {
        event.preventDefault(); items[0].focus();
      }
    },
  }));

  /* === ksfTabs : navigation par onglets au clavier === */
  Alpine.data('ksfTabs', count => ({
    active: 0,
    select(i) { this.active = i; this.$nextTick(() =>
      this.$el.querySelectorAll('[role="tab"]')[i]?.focus()); },
    onKeydown(event) {
      const dir = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (event.key === 'Home') { event.preventDefault(); this.select(0); return; }
      if (event.key === 'End')  { event.preventDefault(); this.select(count - 1); return; }
      if (!(event.key in dir)) return;
      event.preventDefault();
      this.select((this.active + dir[event.key] + count) % count);
    },
  }));
});

/* === ksfConfirm : confirmation via modal Alpine, fallback window.confirm === */
function ksfConfirm(message, options = {}) {
  return window.__ksfModal
    ? window.__ksfModal.confirm(message, options.danger || false)
    : window.confirm(message);
}

/* === ksfAction : action HTTP confirmée via HTMX === */
async function ksfAction(url, { method = 'POST', message = null, danger = false, body = null, target = null } = {}) {
  if (message && !(await ksfConfirm(message, { danger }))) return false;
  const el = target ? document.querySelector(target) : document.body;
  htmx.ajax(method, url, { target: el, swap: 'outerHTML', values: body });
  return true;
}

/* === Événements document === */
document.addEventListener('DOMContentLoaded', () => {
  /* Focus le fragment après un swap HTMX */
  document.body.addEventListener('htmx:afterSwap', event => {
    const target = event.detail.target;
    if (target?.matches?.('#fragment-content, #general-output, #security-output, #maintenance-output, #fragment-result')) {
      target.focus({ preventScroll: true });
    }
  });

  /* Toast ou rendu HTML sur erreur HTMX */
  document.body.addEventListener('htmx:responseError', event => {
    const { xhr, target } = event.detail;
    if (xhr.getResponseHeader('content-type')?.includes('text/html') && xhr.responseText) {
      event.preventDefault();
      target.innerHTML = xhr.responseText;
      target.querySelector('[role="alert"]')?.focus?.({ preventScroll: true });
      return;
    }
    Alpine.store('toasts').error('La requête a échoué.');
  });

  /* Délégation click : [data-ksf-confirm] → ksfAction */
  document.addEventListener('click', ev => {
    const btn = ev.target.closest('[data-ksf-confirm]');
    if (!btn) return;
    ev.preventDefault();
    const url = btn.getAttribute('data-url') || btn.getAttribute('href');
    const method = btn.getAttribute('data-method') || 'POST';
    const message = btn.getAttribute('data-confirm-message') || 'Confirmer l\'action ?';
    const danger = btn.getAttribute('data-confirm-danger') === 'true';
    const target = btn.getAttribute('data-hx-target') || '#fragment-content';
    if (!url) return;
    ksfAction(url, { method, message, danger, target });
  });
});

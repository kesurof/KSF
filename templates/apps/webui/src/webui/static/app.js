/* KSF Web UI — app.js
   Centralise tous les patterns récurrents côté navigateur :
   - ksfFetch / ksfError        : wrapper fetch JSON
   - ksfConfirm                : ouvre la modal déclarée dans base.html
   - $store.toasts              : pile de toasts globale
   - ksfLayout                  : état sidebar (drawer mobile)
   - ksfModal                   : état de la modal de confirmation
   - Alpine.data('ksfList')     : boilerplate read-only réutilisable (HTMX ou fetch)
   Notes :
    * HTMX et Alpine sont des assets locaux versionnés via package-lock.json.
*/

async function ksfFetch(path, options = {}) {
  const response = await fetch(path, options);
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json()
    : { error: await response.text() };
  if (!response.ok) {
    throw new Error(payload.error || `Erreur HTTP ${response.status}`);
  }
  return payload;
}

function ksfError(error) {
  return error instanceof Error ? error.message : 'Erreur inconnue';
}

document.addEventListener('alpine:init', () => {
  /* === Store : toasts globaux === */
  Alpine.store('toasts', {
    items: [],
    seed: 0,
    _id() { return ++this.seed; },
    _push(type, message, ttl) {
      const id = this._id();
      this.items.push({ id, type, message });
      if (ttl > 0) setTimeout(() => this.dismiss(id), ttl);
    },
    success(message, ttl = 4000) { this._push('success', message, ttl); },
    error(message, ttl = 6000)   { this._push('error', message, ttl); },
    warning(message, ttl = 5000) { this._push('warning', message, ttl); },
    info(message, ttl = 4000)    { this._push('info', message, ttl); },
    dismiss(id) { this.items = this.items.filter(t => t.id !== id); },
  });

  /* === Alpine.data : ksfLayout (rail desktop, drawer tablette/mobile) === */
  Alpine.data('ksfLayout', () => ({
    sidebarOpen: window.innerWidth > 1023,
    sidebarCollapsed: false,
    isDrawer: window.innerWidth <= 1023,
    sidebarToggleLabel: 'Replier la navigation',
    init() {
      const mq = window.matchMedia('(max-width: 1023px)');
      const handler = (e) => {
        this.isDrawer = e.matches;
        this.sidebarCollapsed = false;
        this.sidebarOpen = !e.matches;
        this.syncPageState();
      };
      mq.addEventListener('change', handler);
      this.syncPageState();
    },
    syncPageState() {
      this.sidebarToggleLabel = this.isDrawer
        ? (this.sidebarOpen ? 'Fermer le menu' : 'Ouvrir le menu')
        : (this.sidebarCollapsed ? 'Déplier la navigation' : 'Replier la navigation');
      document.documentElement.classList.toggle('sidebar-drawer-open', this.isDrawer && this.sidebarOpen);
    },
    handleNavigation(event) {
      if (this.isDrawer && event.target.closest('.nav-link')) this.sidebarClose();
    },
    sidebarToggle() {
      if (this.isDrawer) {
        this.sidebarOpen = !this.sidebarOpen;
        if (this.sidebarOpen) this.$nextTick(() => this.$el.querySelector('.sidebar-brand').focus());
      } else {
        this.sidebarCollapsed = !this.sidebarCollapsed;
        this.sidebarOpen = !this.sidebarCollapsed;
      }
      this.syncPageState();
    },
    sidebarClose() {
      if (!this.isDrawer || !this.sidebarOpen) return;
      this.sidebarOpen = false;
      this.syncPageState();
      this.$nextTick(() => this.$refs.menuButton.focus());
    },
  }));

  /* === Alpine.data : ksfModal (modal de confirmation) ===
     Expose un handler global window.__ksfModal.confirm(message, danger)
     qui résout une Promise<Boolean>. */
  Alpine.data('ksfModal', () => ({
    open: false,
    message: '',
    danger: false,
    _resolve: null,
    _opener: null,
    init() {
      window.__ksfModal = window.__ksfModal || {};
      window.__ksfModal.confirm = (message, danger = false, opener = document.activeElement) => {
        this.message = message;
        this.danger = !!danger;
        this._opener = opener instanceof HTMLElement ? opener : null;
        this.open = true;
        this._resolve?.(false);
        this.$nextTick(() => this.$refs.cancelButton.focus());
        return new Promise(resolve => { this._resolve = resolve; });
      };
    },
    confirm() {
      this._resolve?.(true);
      this.close();
    },
    cancel() {
      this._resolve?.(false);
      this.close();
    },
    close() {
      this.open = false;
      const opener = this._opener;
      this._opener = null;
      if (opener?.isConnected) this.$nextTick(() => opener.focus());
    },
    trapFocus(event) {
      const focusable = [...this.$refs.body.querySelectorAll('a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])')];
      if (!focusable.length || event.key !== 'Tab') return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    },
  }));

  Alpine.data('ksfTabs', (count) => ({
    active: 0,
    select(index) { this.active = index; this.$nextTick(() => this.$el.querySelectorAll('[role="tab"]')[index].focus()); },
    onKeydown(event) {
      const keys = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
      if (!(event.key in keys) && !['Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? count - 1 : (this.active + keys[event.key] + count) % count;
      this.select(next);
    },
  }));

  Alpine.data('ksfDropdown', () => ({
    open: false,
    toggle() { this.open = !this.open; if (this.open) this.$nextTick(() => this.$refs.menu.querySelector('button:not([disabled]), a[href]')?.focus()); },
    close(restoreFocus = true) { if (!this.open) return; this.open = false; if (restoreFocus) this.$nextTick(() => this.$refs.trigger.focus()); },
    onKeydown(event) {
      if (event.key === 'Escape') { event.preventDefault(); this.close(); }
      if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
      event.preventDefault();
      const items = [...this.$refs.menu.querySelectorAll('button:not([disabled]), a[href]')];
      const index = items.indexOf(document.activeElement);
      items[(index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length]?.focus();
    },
  }));

  Alpine.data('ksfCombobox', () => ({
    open: false,
    query: '',
    active: -1,
    openList() { this.open = true; this.active = -1; },
    close() { this.open = false; this.active = -1; },
    options() { return [...this.$refs.list.querySelectorAll('[role="option"]')]; },
    choose(option) { this.query = option.textContent.trim(); this.close(); this.$refs.input.focus(); },
    onKeydown(event) {
      const options = this.options();
      if (event.key === 'Escape') { this.close(); this.$refs.input.focus(); return; }
      if (event.key === 'Enter' && this.open && this.active >= 0) {
        event.preventDefault(); this.choose(options[this.active]); return;
      }
      if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key) || !options.length) return;
      event.preventDefault(); this.open = true;
      if (event.key === 'Home') this.active = 0;
      else if (event.key === 'End') this.active = options.length - 1;
      else this.active = (this.active + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length;
      this.$refs.input.setAttribute('aria-activedescendant', options[this.active].id);
    },
  }));
});

/* Helper post-Alpine : ouvrir la modal de n'importe quel handler Alpine.
   Utilisation au sein d'une page :
     if (!await ksfConfirm('Supprimer X ?', { danger: true })) return; */
function ksfConfirm(message, options = {}) {
  if (!window.__ksfModal) return window.confirm(message);
  return window.__ksfModal.confirm(message, options.danger || false);
}

/* Helper : exécuter une action POST après confirmation, puis toasts.
   Usage : ksfAction('/api/apps/x/restart', { message: 'Démarrer X ?' }) */
async function ksfAction(url, { method = 'POST', message = null, danger = false, body = null } = {}) {
  if (message && !await ksfConfirm(message, { danger })) return false;
  try {
    const opts = { method, headers: {} };
    if (body !== null) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const result = await ksfFetch(url, opts);
    Alpine.store('toasts').success(result.message || 'Action effectuée.');
    return result || true;
  } catch (error) {
    Alpine.store('toasts').error(ksfError(error));
    return false;
  }
}

/* Helper : Déléguer tous les [data-ksf-confirm] à un seul handler global.
   Usage dans le HTML :
     <button data-ksf-confirm data-url="/api/..." data-method="POST"
             data-confirm-message="..." data-confirm-danger="true">Supprimer</button>
   Le bouton se transforme en appel modal -> fetch -> toast. */
document.addEventListener('DOMContentLoaded', () => {
  document.body.addEventListener('htmx:afterSwap', (event) => {
    const fragment = event.detail.target.matches?.('#fragment-content, #general-output, #security-output, #maintenance-output, #fragment-result')
      ? event.detail.target
      : event.detail.target.querySelector('#fragment-content, #general-output, #security-output, #maintenance-output, #fragment-result');
    if (fragment) fragment.focus({ preventScroll: true });
  });

  document.body.addEventListener('htmx:responseError', (event) => {
    const { xhr, target } = event.detail;
    if (xhr.getResponseHeader('content-type')?.includes('text/html') && xhr.responseText) {
      event.preventDefault();
      target.innerHTML = xhr.responseText;
      target.querySelector('[role="alert"]')?.focus?.({ preventScroll: true });
      return;
    }
    Alpine.store('toasts').error('La requête a échoué.');
  });

  document.addEventListener('click', (ev) => {
    const btn = ev.target.closest('[data-ksf-confirm]');
    if (!btn) return;
    ev.preventDefault();
    const url = btn.getAttribute('data-url');
    const method = btn.getAttribute('data-method') || 'POST';
    const message = btn.getAttribute('data-confirm-message') || 'Confirmer l\'action ?';
    const danger = btn.getAttribute('data-confirm-danger') === 'true';
    if (!url) return;
    ksfAction(url, { method, message, danger }).then((ok) => {
      if (ok && btn.dataset.ksfReload !== undefined) {
        window.location.reload();
      } else if (ok && btn.dataset.ksfRedirect) {
        window.location.assign(btn.dataset.ksfRedirect);
      } else if (ok) {
        // HTMX refresh si container identifié
        const target = btn.getAttribute('data-hx-target');
        if (target && window.htmx) {
          const el = document.querySelector(target);
          if (el) window.htmx.trigger(el, 'ksf-refresh');
        }
      }
    });
  });
});

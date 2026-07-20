/* KSF Web UI — app.js
   Centralise tous les patterns récurrents côté navigateur :
   - ksfFetch / ksfError        : wrapper fetch JSON
   - ksfConfirm                : ouvre la modal déclarée dans base.html
   - $store.toasts              : pile de toasts globale
   - ksfLayout                  : état sidebar (drawer mobile)
   - ksfModal                   : état de la modal de confirmation
   - Alpine.data('ksfList')     : boilerplate read-only réutilisable (HTMX ou fetch)
   Notes :
   * HTMX est chargé en synchrone (avant Alpine) dans base.html.
   * SRI sur les CDN resté à activer lors d'une passe de build (cf. REFACTOR-DESIGN.md Lot 6).
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
    init() {
      window.__ksfModal = window.__ksfModal || {};
      window.__ksfModal.confirm = (message, danger = false) => {
        this.message = message;
        this.danger = !!danger;
        this.open = true;
        this._resolve?.(false);
        return new Promise(resolve => { this._resolve = resolve; });
      };
    },
    confirm() {
      this._resolve?.(true);
      this.open = false;
    },
    cancel() {
      this._resolve?.(false);
      this.open = false;
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

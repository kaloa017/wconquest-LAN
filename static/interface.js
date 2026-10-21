/* Shared navigation, form feedback and dialog behavior. No game rules live here. */
(function (root, factory) {
  const ui = factory();
  if (typeof module === 'object' && module.exports) module.exports = ui;
  else { root.WCInterface = ui; ui.runtime = ui.install(root); }
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const groups = [
    { id: 'country', name: 'Your country', routes: ['territory', 'empire', 'research', 'quests'] },
    { id: 'command', name: 'Command', routes: ['operations', 'battles'] },
    { id: 'economy', name: 'Economy', routes: ['market', 'trading', 'banks', 'stocks'] },
    { id: 'community', name: 'Community', routes: ['chat', 'faction', 'social'] },
    { id: 'world', name: 'World & progress', routes: ['leaderboard', 'playtime', 'space', 'stats'] },
    { id: 'host', name: 'Administration', routes: ['moderation', 'catalog'] }
  ];
  const routes = {
    territory: { name: 'Territory', description: 'Inspect land, build and expand.', public: true },
    empire: { name: 'Country', description: 'Your capital, buildings, ideology and wonders.' },
    research: { name: 'Research', description: 'Choose a focus and follow its prerequisites.' },
    quests: { name: 'Rewards & achievements', description: 'Daily rewards and long-term milestones.' },
    operations: { name: 'Operations', description: 'Command offensives and defensive orders.' },
    battles: { name: 'Battle history', description: 'Review the outcome of recent fighting.', public: true },
    market: { name: 'Resource market', description: 'Sell resources and inspect your income.' },
    trading: { name: 'Trading & gifts', description: 'Negotiate with players and exchange items.' },
    banks: { name: 'Player banks', description: 'Compare loan terms, lend and repay.' },
    stocks: { name: 'Stock exchange', description: 'Buy shares and manage your portfolio.' },
    chat: { name: 'Chat', description: 'Global and private faction conversations.' },
    faction: { name: 'Faction', description: 'Members, shared resources and faction treaties.' },
    social: { name: 'Diplomacy', description: 'Player alliances and agreements.' },
    leaderboard: { name: 'Rankings', description: 'Compare countries and player progress.', public: true },
    playtime: { name: 'Playtime', description: 'Your activity and time spent playing.', public: true },
    space: { name: 'Space program', description: 'Orbital businesses and planetary expeditions.' },
    stats: { name: 'Statistics', description: 'Your country in numbers; world totals for admins.' },
    moderation: { name: 'Moderation', description: 'Player conduct, timeouts and territory disputes.', permission: 'moderator' },
    catalog: { name: 'Game editor', description: 'Edit buildings, wonders and country effects.', permission: 'admin' }
  };
  function canVisit(id, user) {
    const route = routes[id];
    if (!route) return false;
    if (route.permission === 'admin') return !!user?.is_admin;
    if (route.permission === 'moderator') return !!(user?.is_admin || user?.is_moderator);
    return !!user || !!route.public;
  }
  function visibleGroups(user, available = Object.keys(routes), query = '') {
    const search = String(query).trim().toLocaleLowerCase();
    return groups.map(group => ({ ...group, routes: group.routes.filter(id => available.includes(id) && canVisit(id, user)
      && (!search || `${routes[id].name} ${routes[id].description} ${group.name}`.toLocaleLowerCase().includes(search))) }))
      .filter(group => group.routes.length);
  }
  function validateValue(input) {
    if (input.disabled || input.type === 'hidden') return '';
    const value = String(input.value ?? '');
    if (input.required && !value.trim()) return 'Complete this field.';
    if (value && input.type === 'number') {
      const number = Number(value);
      if (!Number.isFinite(number)) return 'Enter a valid number.';
      if (input.min !== '' && input.min !== undefined && number < Number(input.min)) return `Use ${input.min} or more.`;
      if (input.max !== '' && input.max !== undefined && number > Number(input.max)) return `Use ${input.max} or less.`;
      if (input.step && input.step !== 'any') {
        const step = Number(input.step), base = Number(input.min || 0);
        if (step > 0 && Math.abs((number - base) / step - Math.round((number - base) / step)) > 1e-7) return `Use increments of ${input.step}.`;
      }
    }
    if (value && input.minLength > 0 && value.length < input.minLength) return `Use at least ${input.minLength} characters.`;
    if (value && input.maxLength > 0 && value.length > input.maxLength) return `Use no more than ${input.maxLength} characters.`;
    return '';
  }
  function inputValues(scope) {
    return [...scope.querySelectorAll('input[id],textarea[id],select[id]')].filter(input => input.type !== 'file')
      .map(input => ({ id: input.id, value: input.value, checked: input.checked, type: input.type }));
  }
  function restoreValues(scope, values) {
    const inputs = new Map([...scope.querySelectorAll('input[id],textarea[id],select[id]')].map(input => [input.id, input]));
    for (const saved of values) {
      const input = inputs.get(saved.id); if (!input) continue;
      input.value = saved.value;
      if (saved.type === 'checkbox' || saved.type === 'radio') input.checked = saved.checked;
    }
  }
  function errorHint(message) {
    if (/connection|network|interrupted/i.test(message)) return 'Your input is kept. Check your connection and try again.';
    if (/session|log in|authenticated/i.test(message)) return 'Sign in again before retrying this action.';
    if (/busy|wait|too many/i.test(message)) return 'Wait a moment, then try again.';
    return 'Check the details and try again. Your input is kept.';
  }

  function install(w) {
    const doc = w.document;
    if (!doc || doc.documentElement.dataset.interfaceReady) return;
    doc.documentElement.dataset.interfaceReady = 'true';
    const user = () => typeof currentUser === 'undefined' ? null : currentUser;
    const panels = () => typeof PANELS === 'undefined' ? {} : PANELS;
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const state = { group: 'country', query: '', active: 'territory', trigger: null, nextId: 0, queued: false,
      drafts: new Map(), baseline: new Map(), pending: new Map(), inert: new Map(), dialogs: [], bypass: false };
    const scopeSelector = '.panel-content,.admin-panel,.modal-body,.v6-dialog,.trade-room,.auth-form';
    const scopeOf = node => node?.closest?.(scopeSelector);
    const scopeKey = scope => {
      if (!scope) return '';
      if (scope.id) return scope.id;
      const overlay = scope.closest('.modal-overlay,.v6-overlay,.ui-confirm-overlay');
      if (overlay) return `${overlay.id || 'dialog'}:${overlay.querySelector('h2,h3')?.textContent || 'form'}:${scope.classList.contains('trade-room') ? 'trade' : scope.classList.contains('modal-body') ? 'body' : 'dialog'}`;
      return scope.dataset.uiScope ||= `ui-scope-${++state.nextId}`;
    };
    const meaningful = input => !!input.closest('#panel-catalog,#admin-editor,#admin-advertisements,#profile-modal,#chat-filter-settings,#server-settings,[data-ui-drafts]')
      && !['range', 'file', 'hidden'].includes(input.type)
      && !/(?:sort|filter|path|nav-|research-path)/.test(input.id || '')
      && !input.hasAttribute('data-ui-filter');

    function feedback(scope, message, kind = 'status') {
      if (!scope) return;
      let node = [...scope.children].find(child => child.classList?.contains('ui-feedback'));
      if (!node) { node = doc.createElement('div'); node.className = 'ui-feedback'; scope.prepend(node); }
      node.dataset.kind = kind; node.setAttribute('role', kind === 'error' ? 'alert' : 'status');
      node.textContent = message; node.hidden = !message;
    }
    function dirtyStatus(scope) {
      if (!scope) return;
      const key = scopeKey(scope), dirty = state.drafts.has(key);
      let status = [...scope.children].find(child => child.classList?.contains('ui-draft-status'));
      if (!dirty) { status?.remove(); return; }
      if (!status) {
        status = doc.createElement('div'); status.className = 'ui-draft-status'; status.setAttribute('role', 'status');
        const text = doc.createElement('span'); text.textContent = 'Unsaved changes'; status.appendChild(text);
        const discard = doc.createElement('button'); discard.type = 'button'; discard.className = 'btn btn-ghost btn-sm'; discard.textContent = 'Discard changes';
        discard.onclick = () => { restoreValues(scope, state.baseline.get(key) || []); state.drafts.delete(key); dirtyStatus(scope); };
        status.appendChild(discard); scope.prepend(status);
      }
    }
    function clearDraft(scope) {
      if (!scope) return;
      const key = scopeKey(scope); state.drafts.delete(key); state.baseline.set(key, inputValues(scope)); dirtyStatus(scope);
    }
    function markDraft(input) {
      if (!meaningful(input)) return;
      const scope = scopeOf(input); if (!scope) return;
      const key = scopeKey(scope), values = inputValues(scope);
      if (JSON.stringify(values) === JSON.stringify(state.baseline.get(key))) state.drafts.delete(key);
      else state.drafts.set(key, values);
      dirtyStatus(scope);
    }
    function confirmLeave(scope, proceed) {
      if (state.bypass || !scope || !state.drafts.has(scopeKey(scope))) { proceed(); return; }
      if (doc.getElementById('ui-leave-dialog')) return;
      const overlay = doc.createElement('div'); overlay.id = 'ui-leave-dialog'; overlay.className = 'ui-confirm-overlay';
      overlay.innerHTML = '<section class="v6-dialog" role="dialog" aria-modal="true" aria-labelledby="ui-leave-title"><h2 id="ui-leave-title">Keep your changes?</h2><p>You have unsaved changes in this screen.</p><div class="dialog-actions"><button class="btn btn-primary" data-choice="stay">Keep editing</button><button class="btn btn-ghost" data-choice="keep">Keep draft and continue</button><button class="btn btn-danger" data-choice="discard">Discard and continue</button></div></section>';
      overlay.addEventListener('click', event => {
        const choice = event.target.closest('[data-choice]')?.dataset.choice; if (!choice) return;
        if (choice === 'discard') { restoreValues(scope, state.baseline.get(scopeKey(scope)) || []); state.drafts.delete(scopeKey(scope)); dirtyStatus(scope); }
        overlay.remove();
        if (choice !== 'stay') { state.bypass = true; try { proceed(); } finally { state.bypass = false; } }
      });
      doc.body.appendChild(overlay); updateDialogs();
    }

    function updateNavigation() {
      const tabs = doc.querySelector('.sidebar-tabs'); if (!tabs) return;
      tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', 'Features in this group');
      const available = Object.keys(panels());
      const visible = visibleGroups(user(), available, state.query);
      const allVisible = visibleGroups(user(), available);
      if (!allVisible.some(group => group.id === state.group)) state.group = allVisible[0]?.id || 'country';
      const select = doc.getElementById('ui-nav-group');
      if (select) {
        const options = allVisible.map(group => `<option value="${group.id}">${group.name}</option>`).join('');
        if (select.innerHTML !== options) select.innerHTML = options;
        select.value = state.group;
      }
      const shown = new Set(visible.filter(group => state.query || group.id === state.group).flatMap(group => group.routes));
      for (const button of tabs.querySelectorAll('[data-panel]')) {
        const id = button.dataset.panel, item = routes[id];
        button.hidden = !shown.has(id); if (!item) continue;
        button.id ||= 'nav-' + id; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', 'panel-' + id);
        button.classList.toggle('active', id === state.active);
        button.setAttribute('aria-selected', String(id === state.active));
        button.tabIndex = id === state.active && shown.has(id) ? 0 : -1;
        if (button.dataset.uiLabel !== item.name) {
          const icon = typeof menuItems !== 'undefined' ? menuItems[id]?.icon || '' : '';
          const dot = button.querySelector('.dot'); button.replaceChildren();
          const symbol = doc.createElement('span'); symbol.className = 'si'; symbol.setAttribute('aria-hidden', 'true'); symbol.textContent = icon;
          const label = doc.createElement('span'); label.textContent = item.name; button.append(symbol, label);
          if (dot) button.appendChild(dot);
          button.dataset.uiLabel = item.name;
        }
        button.title = item.description;
      }
      const first = [...tabs.querySelectorAll('[data-panel]')].find(button => !button.hidden);
      if (first && !tabs.querySelector('[tabindex="0"]:not([hidden])')) first.tabIndex = 0;
      doc.getElementById('ui-nav-empty').hidden = shown.size > 0;
      doc.getElementById('ui-nav-context').textContent = state.query ? `${shown.size} matching destinations` : `Current section: ${routes[state.active]?.name || 'Territory'}`;
      const summary=doc.getElementById('ui-nav-summary');if(summary)summary.textContent='☰ Menus · '+(routes[state.active]?.name||'Territory');
      for (const [id, item] of Object.entries(routes)) {
        const panel = doc.getElementById('panel-' + id); if (!panel) continue;
        let heading = panel.querySelector('.panel-heading');
        if (!heading) { heading = doc.createElement('header'); heading.className = 'panel-heading'; panel.prepend(heading); }
        if (heading.dataset.uiLabel !== item.name) {
          heading.innerHTML = `<span class="eyebrow">${groups.find(g => g.routes.includes(id))?.name || 'World Conquest'}</span><h2>${item.name}</h2><p>${item.description}</p>`;
          heading.dataset.uiLabel = item.name;
        }
        panel.setAttribute('aria-labelledby', 'nav-' + id);
        panel.setAttribute('role', 'tabpanel');
      }
    }
    function installNavigation() {
      const tabs = doc.querySelector('.sidebar-tabs'); if (!tabs || doc.getElementById('ui-navigation')) return;
      const scrollWrapper = tabs.closest('.scroll-controls');
      if (scrollWrapper) { scrollWrapper.before(tabs); scrollWrapper.remove(); }
      const nav = doc.createElement('nav'); nav.id = 'ui-navigation'; nav.setAttribute('aria-label', 'Game sections');
      nav.innerHTML = '<details id="ui-menu-picker"><summary id="ui-nav-summary">☰ Menus · Territory</summary><div class="ui-menu-controls"><label class="ui-sr-only" for="ui-nav-search">Find a feature</label><input id="ui-nav-search" data-ui-filter type="search" class="form-input" placeholder="Find a menu…" autocomplete="off"><label class="ui-sr-only" for="ui-nav-group">Feature group</label><select id="ui-nav-group" class="form-input" data-ui-filter></select></div><p id="ui-nav-context" class="ui-nav-context"></p></details>';
      tabs.before(nav); nav.querySelector('details').appendChild(tabs);
      const empty = doc.createElement('p'); empty.id = 'ui-nav-empty'; empty.className = 'ui-empty'; empty.hidden = true; empty.textContent = 'No matching menu. Try another name.'; nav.querySelector('details').appendChild(empty);
      doc.getElementById('ui-nav-search').addEventListener('input', event => { state.query = event.target.value; updateNavigation(); });
      doc.getElementById('ui-nav-group').addEventListener('change', event => { state.group = event.target.value; state.query = ''; doc.getElementById('ui-nav-search').value = ''; updateNavigation(); });
      tabs.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
        const items = [...tabs.querySelectorAll('[data-panel]')].filter(button => !button.hidden && !button.disabled);
        const index = items.indexOf(doc.activeElement); if (index < 0 || !items.length) return;
        const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (['ArrowLeft', 'ArrowUp'].includes(event.key) ? -1 : 1) + items.length) % items.length;
        event.preventDefault(); items[index].tabIndex = -1; items[next].tabIndex = 0; items[next].focus();
      });
      if (typeof menuItems !== 'undefined') for (const [id, item] of Object.entries(routes)) if (menuItems[id]) Object.assign(menuItems[id], { name: item.name, desc: item.description });
      w.menuHome = function () {
        return '<label for="ui-mobile-search">Find a feature</label><input class="form-input" id="ui-mobile-search" data-ui-filter type="search" placeholder="Search menus…"><p id="ui-mobile-empty" class="ui-empty" hidden>No matching menu.</p>'
          + visibleGroups(user(), Object.keys(panels())).map(group => `<section class="ui-menu-group"><h3>${group.name}</h3><div class="more-grid">${group.routes.map(id => `<button data-ui-route="${id}" data-ui-search="${escape((routes[id].name + ' ' + routes[id].description).toLowerCase())}" onclick="openExpansionPanel('${id}')"><span aria-hidden="true">${typeof menuItems !== 'undefined' ? menuItems[id]?.icon || '' : ''}</span><strong>${routes[id].name}</strong><small>${routes[id].description}</small></button>`).join('')}</div></section>`).join('');
      };
      const oldShow = w.showPanel;
      w.showPanel = function (id) {
        if (!canVisit(id, user())) { w.toast?.(user() ? 'You do not have access to this section.' : 'Sign in to use this section.', 'error'); return; }
        const current = doc.getElementById('panel-' + state.active);
        const navigate = () => {
          state.active = id; state.group = groups.find(group => group.routes.includes(id))?.id || state.group; state.query = '';
          doc.getElementById('ui-menu-picker').open=false;
          doc.getElementById('ui-nav-search').value = ''; const result = oldShow(id); updateNavigation(); queueEnhance(); return result;
        };
        if (id !== state.active && current && state.drafts.has(scopeKey(current))) return confirmLeave(current, navigate);
        return navigate();
      };
      const oldMobile = w.mobileNav;
      w.mobileNav = function (tab, panel) {
        const id = panel || tab;
        if (!['map', 'more'].includes(id) && !canVisit(id, user())) { w.toast?.('Sign in or ask the host for access.', 'error'); return; }
        const current = doc.getElementById('panel-' + state.active);
        const navigate = () => {
          const result = oldMobile(tab, panel);
          if (!['map', 'more'].includes(id)) { state.active = id; updateNavigation(); }
          const title = doc.getElementById('sheet-title'); if (title) title.textContent = id === 'more' ? 'All features' : routes[id]?.name || title.textContent;
          const sheet = doc.getElementById('mobile-sheet'); if (sheet) sheet.setAttribute('aria-label', title?.textContent || 'Game menu');
          queueEnhance(); return result;
        };
        if (id !== state.active && current && state.drafts.has(scopeKey(current))) return confirmLeave(current, navigate);
        return navigate();
      };
      updateNavigation();
    }

    function wrapRenderers() {
      for (const [id, panel] of Object.entries(panels())) {
        if (panel.f?.uiWrapped) continue;
        const original = panel.f; if (typeof original !== 'function') continue;
        function render(...args) {
          const element = doc.getElementById('panel-' + id);
          if (element && state.drafts.has(scopeKey(element))) { restoreValues(element, state.drafts.get(scopeKey(element))); return; }
          if (element?.dataset.uiRendering === 'true') return;
          if (element) { element.dataset.uiRendering = 'true'; element.setAttribute('aria-busy', 'true'); feedback(element, 'Loading ' + (routes[id]?.name || id) + '…'); }
          const done = () => { if (element) { delete element.dataset.uiRendering; element.setAttribute('aria-busy', 'false'); const status = [...element.children].find(n => n.classList?.contains('ui-feedback')); if (status?.dataset.kind === 'status') status.hidden = true; } queueEnhance(); };
          const fail = error => { feedback(element, 'This section could not load. Your game is safe; choose it again to retry.', 'error'); w.console?.error(error); };
          try {
            const result = original(...args);
            if (result?.then) return result.catch(fail).finally(done);
            done(); return result;
          } catch (error) { fail(error); done(); }
        }
        render.uiWrapped = true; panel.f = render;
      }
    }
    function labelInput(input) {
      if (['hidden', 'submit', 'button'].includes(input.type)) return;
      if (!input.id) input.id = 'ui-field-' + ++state.nextId;
      const label = input.labels?.length ? input.labels[0] : input.closest('label');
      if (label) { if (!label.htmlFor && label.contains(input)) label.htmlFor = input.id; return; }
      const text = input.getAttribute('aria-label') || input.placeholder || input.title || input.id.replace(/[-_]/g, ' ');
      if (!input.getAttribute('aria-label')) input.setAttribute('aria-label', text);
      if (input.type === 'range' || input.type === 'checkbox' || input.type === 'radio') return;
      if (input.previousElementSibling?.classList.contains('ui-field-label')) return;
      const node = doc.createElement('label'); node.className = 'ui-field-label'; node.htmlFor = input.id; node.textContent = text;
      input.before(node);
    }
    function enhance(scope = doc) {
      for (const input of scope.querySelectorAll('input,select,textarea')) labelInput(input);
      for (const button of scope.querySelectorAll('button')) {
        if (!button.hasAttribute('type')) button.type = button.closest('form') ? (button.getAttribute('onclick') ? 'button' : 'submit') : 'button';
        if (/^[✕×✖]$/.test(button.textContent.trim()) && !button.getAttribute('aria-label')) button.setAttribute('aria-label', 'Close dialog');
        if (button.disabled && !button.title) button.title = /completed|owned/i.test(button.textContent) ? 'Already completed or owned.' : 'Unavailable. Check the requirements shown in this section.';
      }
      for (const progress of scope.querySelectorAll('progress:not([aria-label]):not([aria-labelledby])')) progress.setAttribute('aria-label', progress.closest('label')?.textContent.trim().slice(0, 100) || 'Progress');
      for (const table of scope.querySelectorAll('table')) {
        table.querySelectorAll('th:not([scope])').forEach(th => th.scope = 'col');
        if (!table.closest('.ui-table-scroll,.table-scroll,[style*="overflow-x"]')) { const wrap = doc.createElement('div'); wrap.className = 'ui-table-scroll'; wrap.tabIndex = 0; wrap.setAttribute('role', 'region'); wrap.setAttribute('aria-label', 'Scrollable data table'); table.before(wrap); wrap.appendChild(table); }
      }
      for (const form of scope.querySelectorAll(scopeSelector)) {
        const key = scopeKey(form); if (!state.baseline.has(key)) state.baseline.set(key, inputValues(form));
        if (state.drafts.has(key) && !form.dataset.uiDraftRestored) { restoreValues(form, state.drafts.get(key)); form.dataset.uiDraftRestored = 'true'; dirtyStatus(form); }
      }
      for (const empty of scope.querySelectorAll('.empty-state')) empty.setAttribute('role', 'status');
      for (const tab of scope.querySelectorAll('.atab')) { tab.setAttribute('role', 'tab'); tab.setAttribute('aria-selected', String(tab.classList.contains('active'))); tab.tabIndex = tab.classList.contains('active') ? 0 : -1; }
      doc.querySelector('.admin-tabs')?.setAttribute('role', 'tablist');
      for (const form of scope.querySelectorAll('.auth-form')) form.setAttribute('role', 'tabpanel');
      for (const tab of scope.querySelectorAll('.auth-tab')) { const selected = tab.classList.contains('active'); tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1; }
      groupAdvanced(scope);
      updateDialogs();
    }
    function groupAdvanced(scope) {
      const editor = scope.querySelector('#advertisements-editor .ad-editor-grid');
      if (editor && !editor.dataset.uiGrouped) {
        editor.dataset.uiGrouped = 'true';
        const details = doc.createElement('details'); details.className = 'ui-advanced-settings';
        const summary = doc.createElement('summary'); summary.textContent = 'Advanced banner appearance'; details.appendChild(summary);
        const fields = doc.createElement('div'); fields.className = 'ad-editor-grid'; details.appendChild(fields);
        for (const input of editor.querySelectorAll('#ad-background,#ad-text_color,#ad-accent,#ad-border_color,#ad-alternate_color,#ad-color_mode,#ad-cycle_seconds,#ad-font_size,#ad-width,#ad-radius,#ad-alignment')) {
          const label = input.closest('label'); if (label && !details.contains(label)) fields.appendChild(label);
        }
        if (fields.children.length) editor.after(details);
      }
      const country = scope.querySelector('#empire-content');
      if (country && !country.querySelector('.ui-advanced-country')) {
        const cards = [...country.querySelectorAll(':scope > .v4-card')].filter(card => /nuclear programme|nuclear program|EVA|embassies|vehicle loans/i.test(card.querySelector('h3,h4')?.textContent || ''));
        if (cards.length) {
          const details = doc.createElement('details'); details.className = 'ui-advanced-country';
          const summary = doc.createElement('summary'); summary.textContent = 'Advanced country actions · embassies, loans & nuclear program'; details.appendChild(summary);
          cards.forEach(card => details.appendChild(card)); country.appendChild(details);
        }
      }
    }
    function queueEnhance() {
      if (state.queued) return;
      state.queued = true;
      w.setTimeout(() => { state.queued = false; enhance(); }, 0);
    }
    function visibleDialogs() {
      return [...doc.querySelectorAll('.modal-overlay.open,.v6-overlay,.ui-confirm-overlay,.activity-overlay,#tut.open,#battle-report.open,#mobile-sheet.open')]
        .filter(node => !node.hidden && node.style.display !== 'none');
    }
    function focusable(dialog) {
      return [...dialog.querySelectorAll('button,input,select,textarea,a[href],summary,[tabindex="0"]')]
        .filter(node => {
          if (node.disabled || node.type === 'hidden' || node.closest('[hidden],details:not([open]) :not(summary)')) return false;
          for (let parent = node; parent && parent !== dialog; parent = parent.parentElement) {
            const style = w.getComputedStyle(parent); if (style.display === 'none' || style.visibility === 'hidden') return false;
          }
          return true;
        });
    }
    function updateDialogs() {
      const open = visibleDialogs(), old = state.dialogs;
      for (const dialog of open) {
        const box = dialog.querySelector('.modal-box,.v6-dialog,.tut-box,#br-box') || dialog;
        if (box !== dialog) { dialog.removeAttribute('role'); dialog.removeAttribute('aria-modal'); }
        box.setAttribute('role', 'dialog'); box.setAttribute('aria-modal', 'true'); box.tabIndex = -1;
        const heading = box.querySelector('h1,h2,h3');
        if (heading) { if (!heading.id) heading.id = 'ui-dialog-title-' + ++state.nextId; box.setAttribute('aria-labelledby', heading.id); }
        else if (!box.hasAttribute('aria-label')) box.setAttribute('aria-label', 'Game dialog');
        if (!old.includes(dialog)) { dialog.uiReturnFocus = doc.activeElement; (focusable(box)[0] || box).focus({ preventScroll: true }); }
      }
      state.dialogs = open;
      const closed = old.filter(dialog => !open.includes(dialog));
      if (closed.length) { const trigger = closed.at(-1).uiReturnFocus; if (trigger?.isConnected) trigger.focus({ preventScroll: true }); }
    }
    function closeTop(event) {
      const top = state.dialogs.at(-1); if (!top) return false;
      if (event.key === 'Tab') {
        const elements = focusable(top), first = elements[0], last = elements.at(-1);
        if (!first) { event.preventDefault(); top.focus(); }
        else if (event.shiftKey && (doc.activeElement === first || !top.contains(doc.activeElement))) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && (doc.activeElement === last || !top.contains(doc.activeElement))) { event.preventDefault(); first.focus(); }
        event.stopImmediatePropagation(); return true;
      }
      if (event.key !== 'Escape') return false;
      event.preventDefault(); event.stopImmediatePropagation();
      if (top.dataset.requiresAcknowledgement || ['activity-paused', 'timeout-overlay'].includes(top.id)) return true;
      const close = top.querySelector('[data-choice="stay"],[data-close],.modal-header button[aria-label^="Close"],.dialog-top button[aria-label^="Close"],.sheet-heading button[aria-label^="Close"]');
      if (close) close.click();
      else if (top.id === 'tut') w.showTutorial?.(typeof TUT !== 'undefined' ? TUT.length : 99);
      else if (top.id === 'battle-report') top.classList.remove('open');
      return true;
    }
    function groupSettings() {
      const content = doc.getElementById('settings-content'); if (!content || content.querySelector('.ui-settings-tabs')) return;
      const blocks = [...content.children], categories = new Map();
      for (const block of blocks) {
        const title = block.querySelector('h2,h3,h4')?.textContent || '';
        const category = /supporter|donator|username style/i.test(title) ? 'Supporter' : /music|sound/i.test(title) ? 'Sound' : /recovery|security|account|two.factor/i.test(title) ? 'Account' : /rules|privacy/i.test(title) ? 'Information' : 'Appearance';
        if (!categories.has(category)) categories.set(category, []); categories.get(category).push(block);
      }
      const account = doc.querySelector('#profile-modal .account-details');
      if (account && !content.contains(account)) { if (!categories.has('Account')) categories.set('Account', []); categories.get('Account').push(account); }
      const tablist = doc.createElement('div'); tablist.className = 'ui-settings-tabs'; tablist.setAttribute('role', 'tablist'); tablist.setAttribute('aria-label', 'Settings categories');
      const groups = [];
      for (const [index, [category, cards]] of [...categories].entries()) {
        const id = 'ui-settings-' + category.toLowerCase(), section = doc.createElement('section'); section.id = id; section.className = 'ui-settings-page'; section.setAttribute('role', 'tabpanel'); section.hidden = index !== 0;
        const button = doc.createElement('button'); button.type = 'button'; button.className = 'btn btn-ghost'; button.id = id + '-tab'; button.textContent = category; button.setAttribute('role', 'tab'); button.setAttribute('aria-controls', id); button.setAttribute('aria-selected', String(index === 0)); button.tabIndex = index === 0 ? 0 : -1;
        section.setAttribute('aria-labelledby', button.id); cards.forEach(card => section.appendChild(card));
        button.onclick = () => { groups.forEach(pair => { pair.section.hidden = pair.button !== button; pair.button.setAttribute('aria-selected', String(pair.button === button)); pair.button.tabIndex = pair.button === button ? 0 : -1; }); };
        groups.push({ section, button }); tablist.appendChild(button); content.appendChild(section);
      }
      content.prepend(tablist);
      tablist.addEventListener('keydown', event => { if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return; const current = groups.findIndex(pair => pair.button === doc.activeElement); if (current < 0) return; event.preventDefault(); const index = event.key === 'Home' ? 0 : event.key === 'End' ? groups.length - 1 : (current + (event.key === 'ArrowLeft' ? -1 : 1) + groups.length) % groups.length; groups[index].button.click(); groups[index].button.focus(); });
    }

    function installRequestFeedback() {
      if (typeof w.api !== 'function') return;
      const oldApi = w.api;
      w.api = async function (method, path, data) {
        if (method !== 'POST' || /\/api\/(activity|spectate)/.test(path)) return oldApi(method, path, data);
        const generation = typeof sessionGeneration === 'undefined' ? 0 : sessionGeneration;
        const key = `${generation}:${user()?.id || 0}:${path}:${JSON.stringify(data || {})}`;
        if (state.pending.has(key)) return state.pending.get(key);
        const trigger = state.trigger && Date.now() - state.trigger.at < 2000 ? state.trigger.node : null;
        const scope = scopeOf(trigger), saved = scope ? inputValues(scope) : [], revision = scope ? JSON.stringify(saved) : '';
        const originalInputs = scope ? [...scope.querySelectorAll('input,textarea,select')] : [];
        const wasDisabled = trigger?.disabled;
        if (trigger) { trigger.disabled = true; trigger.setAttribute('aria-busy', 'true'); }
        if (scope) feedback(scope, 'Working…');
        const promise = (async () => {
          try {
            const result = await oldApi(method, path, data);
            if (generation !== (typeof sessionGeneration === 'undefined' ? 0 : sessionGeneration)) return result;
            if (result?.error) {
              feedback(scope, result.error + ' ' + errorHint(result.error), 'error');
              // Keep an in-memory copy even if a legacy handler redraws after failure.
              if (scope && [...scope.querySelectorAll('input,select,textarea')].some(meaningful) && !state.drafts.has(scopeKey(scope))) state.drafts.set(scopeKey(scope), saved);
              w.setTimeout(() => {
                if (generation !== (typeof sessionGeneration === 'undefined' ? 0 : sessionGeneration)) return;
                const current = scope?.id ? doc.getElementById(scope.id) : scope;
                if (current?.isConnected) {
                  const latest = state.drafts.get(scopeKey(scope)) || saved;
                  const replaced = originalInputs.some(input => !current.contains(input));
                  if (replaced || current !== scope || JSON.stringify(inputValues(current)) === revision) restoreValues(current, latest);
                  dirtyStatus(current); feedback(current, result.error + ' ' + errorHint(result.error), 'error');
                }
              }, 0);
            } else if (scope) {
              // A delayed save must never mark edits typed while it ran as saved.
              if (JSON.stringify(inputValues(scope)) === revision) clearDraft(scope);
              feedback(scope, result?.message || 'Action completed.', 'success');
            }
            return result;
          } finally {
            if (trigger?.isConnected) { trigger.disabled = !!wasDisabled; trigger.removeAttribute('aria-busy'); }
            state.pending.delete(key); queueEnhance();
          }
        })();
        state.pending.set(key, promise); return promise;
      };
    }

    doc.addEventListener('click', event => {
      const button = event.target.closest?.('button,[role="button"]');
      if (button) state.trigger = { node: button, at: Date.now() };
      const close = button && (button.hasAttribute('data-close') || /closeProfile|closeAdmin|closeGiftModal|closeCommunityDialog/.test(button.getAttribute('onclick') || ''));
      const dialog = close && button.closest('.v6-overlay,.modal-overlay');
      const scope = dialog && [...dialog.querySelectorAll(scopeSelector)].find(node => state.drafts.has(scopeKey(node)));
      if (scope && !state.bypass) { event.preventDefault(); event.stopImmediatePropagation(); confirmLeave(scope, () => button.click()); }
    }, true);
    doc.addEventListener('focusin', event => { const scope = scopeOf(event.target); if (scope && !state.drafts.has(scopeKey(scope))) state.baseline.set(scopeKey(scope), inputValues(scope)); });
    doc.addEventListener('input', event => {
      const input = event.target;
      if (input.id === 'ui-mobile-search') {
        const query = input.value.trim().toLowerCase(); let count = 0;
        doc.querySelectorAll('[data-ui-route]').forEach(button => { button.hidden = !button.dataset.uiSearch.includes(query); if (!button.hidden) count++; });
        doc.querySelectorAll('.ui-menu-group').forEach(group => { group.hidden = ![...group.querySelectorAll('[data-ui-route]')].some(button => !button.hidden); });
        doc.getElementById('ui-mobile-empty').hidden = count > 0; return;
      }
      if (input.matches?.('input,select,textarea')) { markDraft(input); input.removeAttribute('aria-invalid'); doc.getElementById(input.id + '-error')?.remove(); }
    });
    doc.addEventListener('change', event => { if (event.target.matches?.('input,select,textarea')) markDraft(event.target); });
    doc.addEventListener('focusout', event => {
      const input = event.target; if (!input.matches?.('input,textarea') || input.hasAttribute('data-ui-filter')) return;
      const message = validateValue(input); if (!message) return;
      input.setAttribute('aria-invalid', 'true');
      let error = doc.getElementById(input.id + '-error'); if (!error) { error = doc.createElement('small'); error.id = input.id + '-error'; error.className = 'ui-field-error'; error.setAttribute('role', 'alert'); input.after(error); }
      error.textContent = message; input.setAttribute('aria-describedby', [input.getAttribute('aria-describedby'), error.id].filter(Boolean).join(' '));
    });
    doc.addEventListener('keydown', closeTop, true);
    doc.addEventListener('keydown', event => {
      const list = event.target.closest?.('.admin-tabs,.auth-tabs');
      if (!list || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const items = [...list.querySelectorAll('.atab,.auth-tab')], index = items.indexOf(doc.activeElement); if (index < 0) return;
      event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (index + (event.key === 'ArrowLeft' ? -1 : 1) + items.length) % items.length; items[next].click(); items[next].focus(); queueEnhance();
    });
    w.addEventListener('beforeunload', event => { if (state.drafts.size) { event.preventDefault(); event.returnValue = ''; } });
    if (typeof w.buildSettings === 'function') {
      const old = w.buildSettings;
      w.buildSettings = function (...args) {
        const body = doc.querySelector('#profile-modal .modal-body');
        if (body && state.drafts.has(scopeKey(body))) return;
        // Preserve account controls when the preferences renderer replaces its content.
        const content = doc.getElementById('settings-content'), account = doc.querySelector('#profile-modal .account-details');
        if (account && content?.contains(account)) doc.querySelector('#profile-modal .modal-body').appendChild(account);
        const result = old(...args); groupSettings(); queueEnhance(); return result;
      };
    }
    if (typeof w.adminTab === 'function') {
      const old = w.adminTab;
      w.adminTab = function (event, id) {
        const current = doc.querySelector('.admin-panel.active');
        if (current && current.id !== 'admin-' + id && state.drafts.has(scopeKey(current))) {
          const select = doc.getElementById('admin-section-select'), active = [...doc.querySelectorAll('.admin-tabs .atab')].findIndex(button => button.classList.contains('active'));
          if (select && active >= 0) select.value = String(active);
          return confirmLeave(current, () => { old(event, id); queueEnhance(); });
        }
        const result = old(event, id); queueEnhance(); return result;
      };
    }
    for (const [name, id] of [['buildAdvertisementEditor', 'admin-advertisements'], ['buildCatalogEditor', 'panel-catalog'], ['buildBanks', 'panel-banks']]) {
      if (typeof w[name] !== 'function') continue;
      const old = w[name];
      w[name] = function (...args) { const scope = doc.getElementById(id); if (scope && state.drafts.has(scopeKey(scope))) return; return old(...args); };
    }
    for (const name of ['closeProfile', 'closeAdmin', 'closeGiftModal', 'closeCommunityDialog']) {
      if (typeof w[name] !== 'function') continue;
      const old = w[name];
      w[name] = function (...args) {
        const top = state.dialogs.at(-1), scope = top && [...top.querySelectorAll(scopeSelector)].find(node => state.drafts.has(scopeKey(node)));
        if (scope && !state.bypass) return confirmLeave(scope, () => old(...args));
        return old(...args);
      };
    }
    if (typeof w.closeMobileSheet === 'function') {
      const old = w.closeMobileSheet;
      w.closeMobileSheet = function (...args) {
        const current = doc.getElementById('panel-' + state.active);
        if (doc.getElementById('mobile-sheet')?.classList.contains('open') && current && state.drafts.has(scopeKey(current))) return confirmLeave(current, () => old(...args));
        return old(...args);
      };
    }
    if (typeof w.refreshUser === 'function') { const old = w.refreshUser; w.refreshUser = async function (...args) { const result = await old(...args); updateNavigation(); return result; }; }
    if (typeof w.stopPolling === 'function') { const old = w.stopPolling; w.stopPolling = function (...args) { state.drafts.clear(); state.baseline.clear(); return old(...args); }; }
    installNavigation(); wrapRenderers(); installRequestFeedback(); enhance();
    const observer = new w.MutationObserver(records => {
      if (records.some(record => !record.target.closest?.('#map') && (record.type === 'childList' && [...record.addedNodes].some(node => node.nodeType === 1 && !node.classList?.contains('ui-field-label')) || record.type === 'attributes' && record.attributeName === 'class'))) queueEnhance();
    });
    observer.observe(doc.body, { subtree: true, childList: true, attributes: true, attributeFilter: ['class'] });
    return { state, enhance, updateNavigation, groupSettings, feedback, confirmLeave, disconnect: () => observer.disconnect() };
  }
  return { groups, routes, canVisit, visibleGroups, validateValue, inputValues, restoreValues, errorHint, install };
});

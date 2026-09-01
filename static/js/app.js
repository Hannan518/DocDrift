// DocGen shared client helpers: theme, toasts, fetch wrapper, nav.
window.DocGen = (() => {
  'use strict';

  function getCookie(name) {
    for (const cookie of document.cookie.split(';')) {
      const trimmed = cookie.trim();
      if (trimmed.startsWith(name + '=')) {
        return decodeURIComponent(trimmed.slice(name.length + 1));
      }
    }
    return '';
  }

  function csrf() {
    const input = document.querySelector('[name=csrfmiddlewaretoken]');
    return (input && input.value) || getCookie('csrftoken');
  }

  const TOAST_ICONS = {
    success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m8.5 12.5 2.5 2.5 5-6"/></svg>',
    error: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4M12 16h.01"/></svg>',
    warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/></svg>',
    info: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
  };

  function toast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const el = document.createElement('div');
    el.className = `toast toast--${type}`;
    el.setAttribute('role', 'status');

    const icon = document.createElement('span');
    icon.innerHTML = TOAST_ICONS[type] || TOAST_ICONS.info;

    const text = document.createElement('span');
    text.textContent = message; // textContent - never interpolate untrusted HTML

    const close = document.createElement('button');
    close.className = 'toast__close';
    close.setAttribute('aria-label', 'Dismiss');
    close.textContent = '×';
    close.addEventListener('click', () => dismiss());

    el.append(icon, text, close);
    container.appendChild(el);

    const timer = setTimeout(dismiss, 5000);

    function dismiss() {
      clearTimeout(timer);
      el.classList.add('is-leaving');
      setTimeout(() => el.remove(), 200);
    }
  }

  async function api(url, { method = 'POST', body = null } = {}) {
    try {
      const response = await fetch(url, {
        method,
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrf(),
        },
        body: body !== null ? JSON.stringify(body) : undefined,
      });
      let data = null;
      try {
        data = await response.json();
      } catch {
        data = null;
      }
      return { ok: response.ok, status: response.status, data };
    } catch (err) {
      return { ok: false, status: 0, data: { error: 'Network error: ' + err.message } };
    }
  }

  // ---- Theme toggle ----
  function initTheme() {
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;

    const sun = toggle.querySelector('.icon-sun');
    const moon = toggle.querySelector('.icon-moon');

    const render = () => {
      const dark = document.documentElement.getAttribute('data-theme') === 'dark';
      if (sun && moon) {
        sun.classList.toggle('hidden', !dark);
        moon.classList.toggle('hidden', dark);
      }
      toggle.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
    };

    toggle.addEventListener('click', () => {
      const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem('docgen-theme', next); } catch { /* private mode */ }
      render();
    });

    render();
  }

  // ---- Mobile menu ----
  function initMobileMenu() {
    const btn = document.getElementById('mobile-menu-btn');
    const menu = document.getElementById('mobile-menu');
    if (!btn || !menu) return;
    btn.addEventListener('click', () => menu.classList.toggle('is-open'));
  }

  // ---- Active nav link ----
  function initActiveNav() {
    const page = document.body.getAttribute('data-nav');
    if (!page) return;
    document.querySelectorAll(`[data-nav-link="${page}"]`)
      .forEach((link) => link.classList.add('is-active'));
  }

  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initMobileMenu();
    initActiveNav();
  });

  return { toast, api, csrf, getCookie };
})();

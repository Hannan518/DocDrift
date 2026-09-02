// Landing page: reveal-on-enter animations, section rail, smooth jumps.
// All motion respects prefers-reduced-motion (CSS hides the rail + hint).
(() => {
  'use strict';

  const snap = document.getElementById('snap');
  const sections = Array.from(document.querySelectorAll('.snap-section'));
  const railLinks = Array.from(document.querySelectorAll('.snap-rail a'));
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- Reveal on enter (IntersectionObserver) ----
  const revealEls = document.querySelectorAll('[data-reveal]');
  if ('IntersectionObserver' in window && !reducedMotion) {
    const io = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        }
      }
    }, { threshold: 0.25 });
    revealEls.forEach((el) => io.observe(el));
  } else {
    revealEls.forEach((el) => el.classList.add('is-visible'));
  }

  // ---- Smooth jumps for anchor buttons ----
  document.querySelectorAll('.js-jump').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.getElementById(el.dataset.target);
      if (!target) return;
      if (snap) {
        snap.scrollTo({ top: target.offsetTop - snap.offsetTop, behavior: reducedMotion ? 'auto' : 'smooth' });
      } else {
        target.scrollIntoView({ behavior: reducedMotion ? 'auto' : 'smooth' });
      }
    });
  });

  // ---- Section rail: highlight current + click to jump ----
  function setActiveRail(id) {
    railLinks.forEach((a) => {
      a.classList.toggle('is-active', a.dataset.target === id);
    });
  }

  if ('IntersectionObserver' in window && snap) {
    const railIO = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting && entry.intersectionRatio > 0.5) {
          setActiveRail(entry.target.id);
        }
      }
    }, { root: snap, threshold: [0.5] });
    sections.forEach((s) => railIO.observe(s));
  }

  railLinks.forEach((a) => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const target = document.getElementById(a.dataset.target);
      if (target && snap) {
        snap.scrollTo({ top: target.offsetTop, behavior: reducedMotion ? 'auto' : 'smooth' });
      }
    });
  });
})();

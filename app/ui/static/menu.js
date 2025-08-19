// app/ui/static/menu.js
(function () {
  // Create container
  const btn = document.createElement('button');
  btn.setAttribute('aria-label', 'Open menu');
  btn.className = 'fixed top-3 left-3 z-50 rounded-xl bg-slate-800/80 hover:bg-slate-700 px-3 py-2 shadow';
  btn.innerHTML = `
    <div class="w-6 space-y-1">
      <div class="h-0.5 bg-white"></div>
      <div class="h-0.5 bg-white"></div>
      <div class="h-0.5 bg-white"></div>
    </div>
  `;

  // Panel + backdrop
  const backdrop = document.createElement('div');
  backdrop.className = 'fixed inset-0 z-40 bg-black/50 hidden';

  const panel = document.createElement('div');
  panel.className = 'fixed top-0 left-0 z-50 h-full w-72 max-w-[80%] -translate-x-full transition-transform duration-200 bg-slate-900 border-r border-slate-800 shadow-xl';
  panel.innerHTML = `
    <div class="p-4 border-b border-slate-800 flex items-center justify-between">
      <div class="text-lg font-semibold">Menu</div>
      <button aria-label="Close menu" id="menu-close" class="rounded px-2 py-1 bg-slate-800 hover:bg-slate-700">✕</button>
    </div>
    <nav class="p-2">
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/">🏠 Home</a>
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/events">🗓️ Events</a>
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/weather">🌤️ Weather</a>
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/ipx">⚡ IPX Outputs</a>
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/inputs">🎛️ Inputs & Rules</a>
      <a class="block px-3 py-2 rounded hover:bg-slate-800" href="/health/ui">✅ Health</a>
    </nav>
    <div class="px-3 py-3 text-xs text-slate-300/80 border-t border-slate-800">HomeHub</div>
  `;

  function open() {
    backdrop.classList.remove('hidden');
    panel.style.transform = 'translateX(0%)';
  }
  function close() {
    backdrop.classList.add('hidden');
    panel.style.transform = 'translateX(-100%)';
  }

  btn.addEventListener('click', open);
  backdrop.addEventListener('click', close);
  panel.querySelector('#menu-close').addEventListener('click', close);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') close();
  });

  document.body.appendChild(backdrop);
  document.body.appendChild(panel);
  document.body.appendChild(btn);

  // Auto-highlight current path
  const path = location.pathname.replace(/\/+$/, '') || '/';
  panel.querySelectorAll('a').forEach(a => {
    const apath = a.getAttribute('href');
    if (apath === path) a.classList.add('bg-slate-800');
  });
})();


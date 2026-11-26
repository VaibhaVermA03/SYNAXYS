// Apply stored theme before first paint (theme preference only - never auth data).
// Kept as an external file (not inline) so the Content-Security-Policy can use script-src 'self' without 'unsafe-inline'.
try {
  var t = localStorage.getItem('synaxys-theme')
  if (t === 'dark' || (!t && window.matchMedia('(prefers-color-scheme: dark)').matches)) document.documentElement.classList.add('dark')
} catch (e) {}

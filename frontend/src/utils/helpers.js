export function b64enc(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

export function b64dec(str) {
  return Uint8Array.from(atob(str), (c) => c.charCodeAt(0));
}

export function escHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

export function avatarLetter(name) {
  return name.charAt(0).toUpperCase();
}

const AVATAR_PALETTE = [
  '#e53935', '#d81b60', '#8e24aa', '#1976d2',
  '#0097a7', '#388e3c', '#f57c00', '#5d4037',
  '#546e7a', '#00897b',
];

export function avatarBg(name = '') {
  let h = 0;
  for (const c of name) h = (Math.imul(31, h) + c.charCodeAt(0)) | 0;
  return AVATAR_PALETTE[Math.abs(h) % AVATAR_PALETTE.length];
}

export function classNames(...args) {
  return args.filter(Boolean).join(" ");
}

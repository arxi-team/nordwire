// Line illustrations for each step (inline SVG, animated in CSS: .ic-*). One stroke weight, one colour.
const svg = (inner) => `<svg class="ic" viewBox="0 0 120 120" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;

export const ICONS = {
  // a work order being written, line by line
  orders: svg(`
    <rect x="30" y="18" width="60" height="86" rx="7"/>
    <rect x="46" y="12" width="28" height="13" rx="4" class="ic-fill"/>
    <path class="ic-write" style="--d:0s" d="M42 44h36"/>
    <path class="ic-write" style="--d:.35s" d="M42 56h30"/>
    <path class="ic-write" style="--d:.7s" d="M42 68h36"/>
    <path class="ic-write" style="--d:1.05s" d="M42 80h20"/>
    <circle class="ic-dot" cx="76" cy="88" r="6"/>`),
  // the roaster drum turning, heat rising
  roasting: svg(`
    <path class="ic-heat" style="--d:0s" d="M46 26c-4-5 4-8 0-13"/>
    <path class="ic-heat" style="--d:.5s" d="M60 24c-4-5 4-8 0-13"/>
    <path class="ic-heat" style="--d:1s" d="M74 26c-4-5 4-8 0-13"/>
    <circle cx="60" cy="66" r="31"/>
    <g class="ic-spin"><path d="M60 66V40M60 66l22.5 13M60 66L37.5 79"/>
      <ellipse class="ic-fill" cx="60" cy="49" rx="3.4" ry="5" transform="rotate(20 60 49)"/><ellipse class="ic-fill" cx="74" cy="73" rx="3.4" ry="5" transform="rotate(-50 74 73)"/><ellipse class="ic-fill" cx="47" cy="75" rx="3.4" ry="5" transform="rotate(70 47 75)"/></g>
    <circle cx="60" cy="66" r="4" class="ic-fill"/>
    <path d="M36 100h48M42 97v6M78 97v6"/>`),
  // a 1 kg bag filling up
  packaging: svg(`
    <defs><clipPath id="ic-bag"><path d="M37 34h46l6 66c-9 4-49 4-58 0z"/></clipPath></defs>
    <g clip-path="url(#ic-bag)"><rect class="ic-level" x="20" y="34" width="80" height="80"/></g>
    <path d="M37 34h46l6 66c-9 4-49 4-58 0z"/>
    <path d="M35 28h50v6H35z"/>
    <circle cx="60" cy="50" r="4"/>
    <path class="ic-pour" d="M60 6v18"/>`),
  // shipped: a box leaving, the check drawing itself
  delivered: svg(`
    <g class="ic-go"><path d="M28 52l32-14 32 14v34L60 100 28 86z"/><path d="M28 52l32 14 32-14M60 66v34"/></g>
    <path class="ic-speed" style="--d:0s" d="M8 60h12"/><path class="ic-speed" style="--d:.3s" d="M4 72h16"/><path class="ic-speed" style="--d:.6s" d="M10 84h10"/>
    <circle cx="90" cy="32" r="15" class="ic-badge"/>
    <path class="ic-check" d="M83 32l5 5 10-10"/>`),
};

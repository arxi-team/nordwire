// A machine's working loop as a flipbook, for the Raspberry Pi: no 3D library, no WebGL, no script per frame. The image is
// an 8×8 grid of frames (machines.js bakeMachine renders it from the same 3D model; tools/bake-machines.mjs saves it as
// /expometal_flow/static/web/flow/machines/<kind>.webp). line.css steps the box's background through it while the machine works and shows the idle
// frame otherwise; this only says when it works.
export const SHEET = { loop: 5, cols: 8 }; // loop in s · cols × cols frames (line.css .st__sheet uses the same numbers)

export function mountSheet(parent, src, working) {
  const box = document.createElement('div'); box.className = 'st__sheet'; box.setAttribute('aria-hidden', 'true'); box.style.backgroundImage = `url("${src}")`;
  parent.appendChild(box);
  // the station keeps its line icon until the image is decoded (line.css), so the disc is never empty; a failed image leaves the icon
  const img = new Image(); img.src = src; img.decode().then(() => box.classList.add('-ready'), () => box.remove());
  const sync = () => box.classList.toggle('-on', !!working());
  sync(); setInterval(sync, 500);
  return box;
}

// Mock orders (clearly labelled SIMULADO on screen). Shape = what the Odoo adapter will produce later.
const LOTS = [
  ['Espresso Premium', 'Brasil · Etiópia', 25], ['Intenso Blend', 'Brasil · Índia', 40], ['Origem Selecionada', 'Colômbia Huila', 12],
  ['Descafeinado Suave', 'Brasil · Swiss Water', 10], ['Gourmet 100% Arábica', 'Guatemala', 18], ['Clássico Torra Média', 'Brasil · Uganda', 30],
  ['Single Origin Etiópia', 'Yirgacheffe', 8], ['Blend da Casa', 'Brasil · Vietname', 50], ['Cápsulas Lungo', 'Brasil · Etiópia', 15],
  ['Torra Escura Italiana', 'Brasil · Índia', 22], ['Origem Selecionada II', 'Peru Cajamarca', 12], ['Espresso Bar', 'Brasil · Etiópia', 35],
];
let seq = 0;
export function makeOrder(stage = 'orders', now = Date.now()) {
  const [product, origin, kg] = LOTS[seq % LOTS.length]; seq++;
  return { id: `OT-${String(seq).padStart(3, '0')}`, product, origin, kg, stage, enteredAt: now, progress: 0 };
}
export function initialOrders(now = Date.now()) {
  const plan = { orders: 4, roasting: 2, packaging: 2, delivered: 3 }; const out = [];
  for (const [stage, n] of Object.entries(plan)) for (let i = 0; i < n; i++) {
    const o = makeOrder(stage, now - (n - i) * 7 * 60e3);
    o.progress = stage === 'roasting' || stage === 'packaging' ? [0.72, 0.31][i] ?? 0.5 : stage === 'delivered' ? 1 : 0;
    out.push(o);
  }
  // deliver in time order: oldest ids are furthest along
  out.sort((a, b) => ['delivered', 'packaging', 'roasting', 'orders'].indexOf(a.stage) - ['delivered', 'packaging', 'roasting', 'orders'].indexOf(b.stage));
  seq = 0; out.forEach((o) => { seq++; o.id = `OT-${String(seq).padStart(3, '0')}`; });
  return out;
}

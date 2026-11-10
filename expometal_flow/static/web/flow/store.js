// Single source of truth for the dashboard. Every input (screen buttons, keyboard, physical buttons,
// Odoo sync) goes through these actions, so adding a source later never touches the view.
import { STAGES, stageIndex } from './stages.js';
import { makeOrder } from './mock.js';

export function createStore() {
  // starts empty: inputs.js fills it from Odoo, or with the simulation when no Odoo is configured
  const state = { orders: [], active: null, activatedAt: 0, source: 'a ligar', lastMove: null, events: [], funnel: null };
  const subs = new Set();
  const emit = (why) => subs.forEach((fn) => fn(state, why));
  const log = (text, stage) => { state.events = [{ text, stage, at: Date.now() }, ...state.events].slice(0, 6); };

  return {
    state,
    subscribe(fn) { subs.add(fn); fn(state, 'init'); return () => subs.delete(fn); },

    /** A step was triggered (button press). Focus it and, in the demo, move the next order into it. */
    activate(stageId, { origin = 'ecrã', move = true, focus = null, view = false } = {}) {
      const i = stageIndex(stageId); if (i < 0) return;
      state.active = stageId; state.activatedAt = Date.now(); state.lastMove = null;
      // live Odoo data: the cards are the truth; a press only focuses (Odoo itself moves the orders)
      if (state.source === 'odoo') {
        move = false;
        const o = (focus && state.orders.find((x) => (x.focusKey ?? x.id) === focus && x.stage === stageId)) || (focus && state.orders.find((x) => x.id === focus)) || state.orders.filter((x) => x.stage === stageId).sort((a, b) => b.enteredAt - a.enteredAt)[0];
        // a look (touch/key) only focuses; the event log is for what happens in Odoo
        if (o) { state.lastMove = o.id; if (!view) log(`${o.id} · ${STAGES[i].verb}`, stageId); }
      }
      if (move) {
        if (i === 0) { const o = makeOrder('orders'); state.orders.push(o); state.lastMove = o.id; log(`${o.id} · ${STAGES[0].verb}`, stageId); }
        else {
          const prev = STAGES[i - 1].id;
          const next = state.orders.filter((o) => o.stage === prev).sort((a, b) => a.enteredAt - b.enteredAt)[0];
          if (next) {
            next.stage = stageId; next.enteredAt = Date.now(); next.progress = stageId === 'delivered' ? 1 : 0.04; state.lastMove = next.id;
            log(`${next.id} · ${STAGES[i].verb}`, stageId);
          }
        }
        // keep the delivered column short: the oldest pickings leave the board
        const done = state.orders.filter((o) => o.stage === 'delivered');
        if (done.length > 5) state.orders = state.orders.filter((o) => o !== done.sort((a, b) => a.enteredAt - b.enteredAt)[0]);
      }
      emit({ type: 'activate', stage: stageId, origin, view });
    },

    /** Work in progress advances on its own (roasting/packaging progress bars). */
    tick(dt) {
      if (state.source === 'odoo') return; // progress comes from the work orders in Odoo
      let changed = false;
      for (const o of state.orders) if ((o.stage === 'roasting' || o.stage === 'packaging') && o.progress < 0.97) { o.progress = Math.min(0.97, o.progress + dt / (o.stage === 'roasting' ? 180e3 : 120e3)); changed = true; }
      if (changed) emit({ type: 'tick' });
    },

    /** Odoo adapter (server /api/flow/odoo + SSE "odoo"): real records in the same shape as mock.js, plus the funnel. */
    replaceOrders(orders, source = 'odoo', funnel = null) { state.orders = orders; state.source = source; state.funnel = funnel; emit({ type: 'data' }); },
    clearFocus() { state.active = null; emit({ type: 'clear' }); },
  };
}

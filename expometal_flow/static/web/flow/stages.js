// The four steps of the mini coffee operation. `color` = colour of the physical button on the table
// (placeholders until the real button colours are confirmed — change them here only). One physical button per step (later: Nordwire module →
// POST /api/flow/press {stage}). `odoo` documents where the cards will come from once integrated.
export const STAGES = [
  { id: 'orders',    key: '1', color: '#4F8EF7', button: 'azul', name: 'Ordens de Trabalho',   short: 'Ordens',    verb: 'Nova ordem planeada',   odoo: { model: 'mrp.production', state: ['draft', 'confirmed'] } },
  { id: 'roasting',  key: '2', color: '#F0A531', button: 'âmbar', name: 'Torra',                short: 'Torra',     verb: 'Lote em torragem',      odoo: { model: 'mrp.workorder', workcenter: 'Torrador', state: ['progress'] } },
  { id: 'packaging', key: '3', color: '#EE6047', button: 'vermelho', name: 'Embalamento',          short: 'Embalagem', verb: 'Lote em embalamento',   odoo: { model: 'mrp.workorder', workcenter: 'Embalamento', state: ['progress'] } },
  { id: 'delivered', key: '4', color: '#3FBF86', button: 'verde', name: 'Entregue · Pickings',  short: 'Entregues', verb: 'Picking expedido',      odoo: { model: 'stock.picking', picking_type: 'outgoing', state: ['done'] } },
];
export const stageIndex = (id) => STAGES.findIndex((s) => s.id === id);

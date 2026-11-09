# -*- coding: utf-8 -*-
"""PDA page for setting up the next MO on a Nord-controlled machine: the
operator scans the MO's QR code (its name, shown on the MO form) and the
MO's next open work order (the operation it is waiting for, e.g. Torragem)
is set up: its Core resource waits in "Setup" until the machine's own port
starts it. The setup travels to the Core as a 'setup' floor event on the
work order (mrp.workorder._nord_sync_notify_floor_event), same channel as
a Shop Floor start/pause.

A scan is the setup (no confirm button): the field is cleared and keeps the
focus, ready for the next scan, with no on-screen keyboard (inputmode none:
it would cover the list). It is a plain text input: a PDA's built-in
scanner types the code followed by Enter, which needs no camera access
(browsers only allow the camera on HTTPS).

The page is a small menu app (screens switched in the page, the hash is the
screen). The scan field is on every screen and always focused, so a scan is
recognised wherever the operator is. Screens: Lista de MO (below), Em curso (the MOs a
machine is running, with the buttons) and Estado dos postos (a summary per
work center). All of them reuse the endpoints below.

The list shows the MOs still to do, grouped by the work center of the
operation each one is waiting for (the same one a scan would set up), so the
operator can see what is queued on each machine, refreshed after every scan
and every 30 s. A card whose machine is running it (on a stop-tracking work
center) has a "Não OK" button: one rejected unit for that MO
(mrp.workorder.action_nord_sync_not_ok), and the Entregar screen picks a
running MO and a quantity (the planned one by default) to deliver and close
it with (mrp.production._nord_sync_demo_deliver). Results show in a banner fixed at
the bottom, so they are seen wherever the list is scrolled to.
"""
import json
import logging
import threading

import requests

from odoo import fields, modules
from odoo.exceptions import UserError
from odoo.http import Controller, request, route


# Fair demo: after a PDA action the Core is told to fetch now (its
# /nord_sync/pda/pull, local network only) instead of on its next sync tick
# (5 min), and an optional webhook URL (nord_sync.demo_webhook_url) gets a
# POST {event, at, source, ...}. URL of the pull: nord_sync.demo_core_pull_url
# if set. Both go out after the commit, off the request's thread.
_logger = logging.getLogger(__name__)

NORD_SYNC_DEMO_TIMEOUT_SECONDS = 5
NORD_SYNC_DEMO_DEFAULT_CORE_PULL_URL = 'http://localhost:8079/nord_sync/pda/pull'


def _post_after_commit(env, url, body, headers=None):
    if not url or modules.module.current_test:
        return

    def _post():
        try:
            requests.post(url, json=body, headers=headers or {}, timeout=NORD_SYNC_DEMO_TIMEOUT_SECONDS)
        except Exception as exc:
            _logger.warning('nord_sync: demo POST to %s failed: %s', url, exc)

    env.cr.postcommit.add(lambda: threading.Thread(target=_post, daemon=True).start())


def wake_core(env):
    """Asks the Core to fetch this client's queue now."""
    url = env['ir.config_parameter'].sudo().get_param('nord_sync.demo_core_pull_url') or NORD_SYNC_DEMO_DEFAULT_CORE_PULL_URL
    _post_after_commit(env, url, {})


def webhook(env, event, data):
    """POSTs {event, at, source, ...data} to nord_sync.demo_webhook_url."""
    url = env['ir.config_parameter'].sudo().get_param('nord_sync.demo_webhook_url')
    _post_after_commit(env, url, {'event': event, 'at': str(fields.Datetime.now()), 'source': 'odoo', **data})

_PAGE = """<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#112138">
<link rel="manifest" href="/nordwire/pda.webmanifest">
<link rel="apple-touch-icon" href="/nord_sync_mrp/static/src/img/pda-192.png">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Nord PDA">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Nord PDA</title>
<style>
  :root { --bg: #eef0f3; --surface: #fff; --text: #14202f; --muted: #5d6877; --border: rgba(17, 33, 56, .1); --border2: rgba(17, 33, 56, .22); --hover: rgba(17, 33, 56, .08); --navy: #112138; --navy-hover: #0c1726; --on-navy: #fff; --success: #1e8e3e; --success-bg: rgba(30, 142, 62, .12); --warning: #b45f06; --warning-bg: rgba(245, 158, 11, .18); --danger: #d93025; --danger-bg: rgba(217, 48, 37, .1); --neutral: #6b7280; --neutral-bg: rgba(107, 114, 128, .14); --shadow: 0 1px 3px rgba(0, 0, 0, .07); --shadow-lg: 0 6px 24px rgba(0, 0, 0, .18); --bar-h: 64px; }
  @media (prefers-color-scheme: dark) { :root { --bg: #0a1628; --surface: #101f35; --text: #e8edf4; --muted: #9aa8bc; --border: rgba(60, 92, 140, .35); --border2: rgba(60, 92, 140, .7); --hover: rgba(255, 255, 255, .07); --navy: #2f5a96; --navy-hover: #3a6bb0; --success: #4cc26a; --success-bg: rgba(76, 194, 106, .16); --warning: #f0b84a; --warning-bg: rgba(240, 184, 74, .16); --danger: #ff6b61; --danger-bg: rgba(255, 107, 97, .16); --neutral: #9aa8bc; --neutral-bg: rgba(154, 168, 188, .16); --shadow: 0 1px 3px rgba(0, 0, 0, .35); --shadow-lg: 0 8px 32px rgba(0, 0, 0, .55); } }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  html { color-scheme: light dark; }
  body { font-family: 'DM Sans', system-ui, -apple-system, 'Segoe UI', sans-serif; font-size: 16px; margin: 0; min-height: 100vh; min-height: 100dvh; background: var(--bg); color: var(--text); -webkit-font-smoothing: antialiased; padding-bottom: calc(var(--bar-h) + env(safe-area-inset-bottom) + 24px); }
  button { font: inherit; color: inherit; touch-action: manipulation; cursor: pointer; }
  input, select { width: 100%; height: 48px; font: inherit; padding: 0 14px; border-radius: 10px; border: 1px solid var(--border2); background: var(--surface); color: var(--text); }
  :focus-visible { outline: 3px solid var(--navy); outline-offset: 2px; }

  /* Header: brand, machine picker and the scan field, always visible */
  .top { position: sticky; top: 0; z-index: 20; background: var(--navy); color: var(--on-navy); padding: calc(10px + env(safe-area-inset-top)) 14px 12px; box-shadow: var(--shadow); }
  .top-row { display: flex; align-items: center; gap: 10px; }
  .top h1 { margin: 0; font-size: 17px; font-weight: 800; letter-spacing: -.01em; flex: 1; }
  .top h1 small { display: block; font-size: 11px; font-weight: 500; opacity: .7; letter-spacing: .02em; }
  .sync { font-size: 11px; opacity: .75; display: flex; align-items: center; gap: 6px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: #5ee08a; box-shadow: 0 0 0 0 rgba(94, 224, 138, .7); animation: pulse 2s infinite; }
  .dot.off { background: #ff8a80; animation: none; }
  @keyframes pulse { 70% { box-shadow: 0 0 0 7px rgba(94, 224, 138, 0); } 100% { box-shadow: 0 0 0 0 rgba(94, 224, 138, 0); } }
  .chip { display: block; width: 100%; margin-top: 10px; height: 48px; padding: 0 16px; border: 2px solid rgba(255, 255, 255, .3); border-radius: 12px; background: rgba(255, 255, 255, .16); color: var(--on-navy); font-size: 17px; font-weight: 800; text-align: left; }
  .chip[hidden] { display: none; }
  .chip small { font-weight: 600; opacity: .75; margin-left: 8px; }
  .wcgrid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  .wcb { display: flex; flex-direction: column; justify-content: center; gap: 4px; min-height: 104px; padding: 14px; border: 2px solid var(--border2); border-radius: 16px; background: var(--surface); box-shadow: var(--shadow); text-align: left; }
  .wcb b { font-size: 22px; font-weight: 800; letter-spacing: -.01em; overflow-wrap: anywhere; }
  .wcb small { font-size: 14px; font-weight: 600; color: var(--muted); }
  .wcb:active { transform: scale(.97); }
  .wcb.on { background: var(--navy); border-color: var(--navy); color: var(--on-navy); }
  .wcb.on small { color: var(--on-navy); opacity: .8; }
  .wcb.all { grid-column: 1 / -1; min-height: 72px; }
  .top select { margin-top: 10px; height: 64px; padding: 0 16px; border: 2px solid rgba(255, 255, 255, .3); border-radius: 12px; background: rgba(255, 255, 255, .16); color: var(--on-navy); font-size: 22px; font-weight: 800; letter-spacing: -.01em; }
  .top select option { color: #14202f; }
  .scan { position: relative; margin-top: 10px; }
  .scan svg { position: absolute; left: 13px; top: 50%; transform: translateY(-50%); width: 22px; height: 22px; opacity: .6; pointer-events: none; }
  .scan input { height: 52px; padding-left: 46px; padding-right: 76px; font-size: 17px; font-weight: 600; border: 2px solid transparent; }
  .scan input:focus { outline: 0; border-color: #5ee08a; }
  .scan input::placeholder { font-weight: 500; color: var(--muted); }

  .top { transition: background-color .2s; }
  .top.deliver { background: #f5b800; color: #1f1700; }
  .top.deliver .chip { background: rgba(31, 23, 0, .1); border-color: rgba(31, 23, 0, .3); color: #1f1700; }
  .top.deliver .sync { opacity: .8; }
  .scan.deliver input { border-color: #ffb74d; }
  .scan.deliver input:focus { border-color: #ffb74d; }
  .read { position: absolute; right: 6px; top: 6px; height: 40px; padding: 0 16px; border: 0; border-radius: 8px; background: var(--navy); color: var(--on-navy); font-weight: 800; }
  .read:active { background: var(--navy-hover); }
  #cam { position: fixed; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: 50; background: #000; }
  .btn.camclose { display: none; position: fixed; z-index: 51; left: 14px; right: 14px; bottom: 24px; }
  .btn.camclose.on { display: flex; }
  main { padding: 14px; max-width: 720px; margin: 0 auto; }
  .screen { display: none; }
  .screen.on { display: block; animation: in .18s ease-out; }
  @keyframes in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
  h2.sec { display: flex; justify-content: space-between; align-items: center; margin: 22px 2px 8px; font-size: 12px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
  h2.sec:first-child { margin-top: 4px; }
  h2.sec .n { background: var(--neutral-bg); color: var(--text); border-radius: 999px; padding: 2px 9px; letter-spacing: 0; font-size: 12px; }

  /* Home tiles */
  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .tile { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; min-height: 96px; padding: 14px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: var(--shadow); text-align: left; }
  .tile:active { background: var(--hover); transform: scale(.98); }
  .tile b { font-size: 30px; line-height: 1.1; font-weight: 800; letter-spacing: -.02em; }
  .tile span { font-size: 13px; font-weight: 600; color: var(--muted); }
  .tile.run b { color: var(--success); } .tile.set b { color: var(--warning); } .tile.stp b { color: var(--danger); }
  .hint { margin: 0 2px 14px; color: var(--muted); font-size: 13px; line-height: 1.4; }

  /* MO cards */
  .mo { position: relative; margin-bottom: 10px; padding: 14px 14px 14px 18px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: var(--shadow); overflow: hidden; }
  .mo::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 6px; background: var(--border2); }
  .mo.running::before { background: var(--success); } .mo.setup::before { background: var(--warning); } .mo.stopped::before { background: var(--danger); }
  .mo-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; }
  .mo-name { font-size: 18px; font-weight: 800; letter-spacing: -.01em; overflow-wrap: anywhere; }
  .mo-prod { margin-top: 2px; font-size: 15px; color: var(--text); overflow-wrap: anywhere; }
  .mo-meta { margin-top: 6px; display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; color: var(--muted); font-weight: 500; }
  .mo-meta b { color: var(--text); font-weight: 700; }
  .pill { flex: none; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; background: var(--neutral-bg); color: var(--neutral); white-space: nowrap; }
  .pill.running { background: var(--success-bg); color: var(--success); } .pill.setup { background: var(--warning-bg); color: var(--warning); } .pill.stopped { background: var(--danger-bg); color: var(--danger); }
  .pill.urgent { background: var(--danger-bg); color: var(--danger); }
  .actions { display: flex; gap: 8px; margin-top: 12px; }
  .btn { flex: 1; min-height: 52px; padding: 0 16px; border: 1px solid transparent; border-radius: 12px; background: var(--navy); color: var(--on-navy); font-weight: 700; font-size: 16px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
  .btn:active { background: var(--navy-hover); transform: scale(.98); }
  .btn:disabled { opacity: .55; }
  .btn.ok { background: var(--success); color: #fff; }
  .btn.danger { background: var(--danger-bg); color: var(--danger); border-color: var(--danger); }
  .btn.alt { background: var(--surface); color: var(--text); border-color: var(--border2); }
  .btn.sm { min-height: 44px; font-size: 14px; }
  .empty { text-align: center; color: var(--muted); padding: 40px 16px; }
  .empty svg { width: 44px; height: 44px; opacity: .45; margin-bottom: 8px; }

  /* Machine status */
  .mc { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px; margin-bottom: 8px; border: 1px solid var(--border); border-radius: 14px; background: var(--surface); box-shadow: var(--shadow); }
  .mc b { font-size: 17px; } .mc small { display: block; margin-top: 2px; color: var(--muted); font-size: 13px; }
  .mc .led { width: 14px; height: 14px; border-radius: 50%; background: var(--neutral); flex: none; }
  .mc .led.running { background: var(--success); } .mc .led.setup { background: var(--warning); } .mc .led.stopped { background: var(--danger); }
  .mc .l { display: flex; align-items: center; gap: 12px; min-width: 0; }

  /* Deliver sheet */
  .qty { display: grid; grid-template-columns: 64px minmax(0, 1fr) 64px; gap: 10px; margin: 16px 0; }
  .qty .btn { min-height: 64px; font-size: 28px; }
  .qty input { height: 64px; text-align: center; font-size: 30px; font-weight: 800; }

  /* Bottom tab bar */
  .tabs { position: fixed; left: 0; right: 0; bottom: 0; z-index: 20; display: grid; grid-template-columns: repeat(4, 1fr); height: calc(var(--bar-h) + env(safe-area-inset-bottom)); padding-bottom: env(safe-area-inset-bottom); background: var(--surface); border-top: 1px solid var(--border2); }
  .tabs button { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 3px; border: 0; background: none; color: var(--muted); font-size: 12px; font-weight: 700; }
  .tabs button svg { width: 24px; height: 24px; }
  .tabs button.on { color: var(--navy); }
  @media (prefers-color-scheme: dark) { .tabs button.on { color: #8fb4ee; } }
  .tabs button.on::before { content: ''; position: absolute; top: 0; left: 22%; right: 22%; height: 3px; border-radius: 0 0 3px 3px; background: currentColor; }
  .tabs .badge { position: absolute; top: 6px; left: calc(50% + 8px); min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--danger); color: #fff; font-size: 11px; line-height: 18px; text-align: center; }
  .tabs .badge:empty { display: none; }

  /* Toast */
  .msg { position: fixed; left: 14px; right: 14px; bottom: calc(var(--bar-h) + env(safe-area-inset-bottom) + 12px); z-index: 30; max-width: 692px; margin: 0 auto; padding: 14px 16px; border-radius: 14px; font-weight: 700; display: none; box-shadow: var(--shadow-lg); border: 2px solid var(--border2); background: var(--surface); }
  .msg.ok { display: block; color: var(--success); border-color: var(--success); animation: in .15s ease-out; }
  .msg.err { display: block; color: var(--danger); border-color: var(--danger); animation: in .15s ease-out; }
  .brand { margin: 28px 0 0; text-align: center; pointer-events: none; user-select: none; }
  .brand img { height: 20px; opacity: .6; }
  @media (prefers-reduced-motion: reduce) { * { animation: none !important; transition: none !important; } }
</style>
</head>
<body>
<header class="top">
  <div class="top-row">
    <h1>Nord PDA<small id="who">Chão de fábrica</small></h1>
    <div class="sync"><i class="dot" id="dot"></i><span id="sync">a carregar</span></div>
  </div>
  <button type="button" id="wc-chip" class="chip" data-go="home" hidden></button>
  <div class="scan">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:#14202f"><path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3M7 12h10"/></svg>
    <input id="code" autofocus autocomplete="off" autocapitalize="off" spellcheck="false" inputmode="none" aria-label="QR da MO" placeholder="Ler o QR da MO">
    <button type="button" id="read" class="read" aria-label="Ler QR">Ler</button>
  </div>
  <video id="cam" playsinline muted hidden></video>
</header>
<main>
  <section id="home" class="screen on"><h2 class="sec">Escolher posto</h2><div id="wc-grid" class="wcgrid"></div></section>
  <section id="list" class="screen"><h2 class="sec">Em espera <span class="n" id="n-list"></span></h2><div data-view="list"></div></section>
  <section id="running" class="screen"><h2 class="sec">Em curso <span class="n" id="n-running"></span></h2><div data-view="running"></div></section>
  <section id="deliver" class="screen"><h2 class="sec">Entrega</h2><div class="hint">Leia o QR da MO para confirmar a entrega.</div><div data-view="deliver"></div></section>
  <footer class="brand"><picture><source srcset="/nord_sync_mrp/static/src/img/logo_nordwire_white.svg" media="(prefers-color-scheme: dark)"><img src="/nord_sync_mrp/static/src/img/logo_nordwire.svg" alt="Nordwire"></picture></footer>
</main>
<button type="button" class="btn camclose" id="camclose">Cancelar leitura</button>
<div id="msg" class="msg" role="status" aria-live="polite"></div>
<nav class="tabs" aria-label="Navegação">
  <button type="button" data-go="home"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/></svg>Início</button>
  <button type="button" data-go="list"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>Fila<i class="badge" id="b-list"></i></button>
  <button type="button" data-go="running"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z"/></svg>Em curso<i class="badge" id="b-run"></i></button>
  <button type="button" data-go="deliver"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7h11v9H3zM14 10h4l3 3v3h-7zM7 19a1.5 1.5 0 1 0 0-.01M17 19a1.5 1.5 0 1 0 0-.01"/></svg>Entrega</button>
</nav>
<script>
const $ = (id) => document.getElementById(id);
const code = $('code');
async function call(route, params) {
  const res = await fetch(route, {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({jsonrpc: '2.0', method: 'call', params})});
  const body = await res.json();
  if (body.error) throw new Error(body.error.data && body.error.data.message || body.error.message);
  return body.result;
}
const FLOOR = {running: 'A trabalhar', setup: 'Em setup', stopped: 'Parada'};
const esc = (t) => String(t).replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ICON_OK = '<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>';
const empty = (t) => `<div class="empty">${ICON_OK.replace('class="ic"', '')}<div>${t}</div></div>`;
const pill = (o) => FLOOR[o.floor] ? `<span class="pill ${o.floor}">${FLOOR[o.floor]}</span>` : (o.selected_wc ? '<span class="pill setup">Selecionada</span>' : o.in_progress ? '<span class="pill">Iniciada</span>' : '<span class="pill">Em espera</span>');

let groups = [];
let deliveries = [];
const all = () => groups.flatMap((g) => g.orders.map((o) => Object.assign({wc: g.workcenter}, o)));
// Em curso: working now, or selected on a work center and not stopped; the rest (stopped ones included) waits
const active = (o) => o.floor === 'running' || (!!o.selected_wc && o.floor !== 'stopped');
const waiting = (o) => !active(o);

const card = (o, opts = {}) => `<div class="mo ${o.floor}">
  <div class="mo-head"><div><div class="mo-name">${esc(o.name)}</div><div class="mo-prod">${esc(o.product)}</div></div>${pill(o)}</div>
  <div class="mo-meta"><span>Posto <b>${esc(o.selected_wc || o.wc)}</b></span><span>Operação <b>${esc(o.operation)}</b></span><span>Qtd <b>${esc(o.qty)}</b></span>${o.sale ? `<span>Venda <b>${esc(o.sale)}</b></span>` : ''}${o.not_ok ? `<span style="color:var(--danger)">Não OK <b style="color:var(--danger)">${o.not_ok}</b></span>` : ''}</div>
  ${opts.start ? `<div class="actions"><button type="button" class="btn ok" data-start="${esc(o.name)}">Start</button></div>` : ''}
  ${opts.actions ? `<div class="actions"><button type="button" class="btn danger notok" data-mo="${esc(o.name)}">Não OK (+1)</button><button type="button" class="btn alt" data-close="${esc(o.name)}">Fechar MO</button></div>` : ''}
</div>`;

const VIEWS = {
  list: () => { const l = all().filter(waiting); return l.length ? l.map((o) => card(o, {start: true})).join('') : empty('Nada em espera.'); },
  running: () => { const l = all().filter(active); return l.length ? l.map((o) => card(o, {actions: true})).join('') : empty('Nada em curso.'); },
  deliver: () => deliveries.length ? '<h2 class="sec">Por entregar <span class="n">' + deliveries.length + '</span></h2>' + deliveries.map((d) => `<div class="mo"><div class="mo-head"><div><div class="mo-name">${esc(d.name)}</div><div class="mo-prod">${esc(d.product)}</div></div><span class="pill running">Fechada</span></div><div class="mo-meta"><span>Qtd <b>${esc(d.qty)}</b></span>${d.sale ? `<span>Venda <b>${esc(d.sale)}</b></span>` : ''}<span>Entrega <b>${esc(d.delivery)}</b></span></div></div>`).join('') : empty('Nenhuma MO fechada por entregar.'),
};

function render() {
  const a = all();
  const nw = a.filter(waiting).length, na = a.filter(active).length;
  $('b-list').textContent = nw || ''; $('b-run').textContent = na || '';
  $('n-list').textContent = nw; $('n-running').textContent = na;
  document.querySelectorAll('[data-view]').forEach((el) => { el.innerHTML = VIEWS[el.dataset.view](); });
}
function stamp(ok) {
  $('dot').className = 'dot' + (ok ? '' : ' off');
  $('sync').textContent = ok ? 'atualizado ' + new Date().toLocaleTimeString('pt-PT', {hour: '2-digit', minute: '2-digit'}) : 'sem ligação';
}
async function refreshTodo() {
  try { groups = await call('/nordwire/pda/todo', {}); stamp(true); } catch (e) { stamp(false); return; }
  try { deliveries = await call('/nordwire/pda/deliveries', {}); } catch (e) {}
  render();
}

// Navigation: the hash is the screen, so the device's back button works
let current = 'home';
const go = (name) => { location.hash = name === 'home' ? '' : name; };
function showScreen() {
  const name = location.hash.slice(1);
  const screen = $(name) && $(name).classList.contains('screen') ? name : 'home';
  document.querySelectorAll('.screen').forEach((el) => el.classList.toggle('on', el.id === screen));
  document.querySelectorAll('.tabs button').forEach((b) => b.classList.toggle('on', b.dataset.go === screen));
  current = screen;
  if (typeof renderWc === 'function') renderWc();
  document.querySelector('.scan').classList.toggle('deliver', screen === 'deliver');
  document.querySelector('.top').classList.toggle('deliver', screen === 'deliver');
  $('who').textContent = screen === 'deliver' ? 'MODO ENTREGA' : 'Chão de fábrica';
  document.querySelector('meta[name=theme-color]').content = screen === 'deliver' ? '#f5b800' : '#112138';
  code.placeholder = screen === 'deliver' ? 'Ler a MO a entregar' : 'Ler o QR da MO';
  window.scrollTo(0, 0);
  code.focus();
  refreshTodo();
}
window.addEventListener('hashchange', showScreen);
document.addEventListener('click', (e) => { const nav = e.target.closest('[data-go]'); if (nav) go(nav.dataset.go); });
// The scan field keeps the focus: a tap on a button must not take it, or the field
// grabs it back mid-tap and the tap is missed. click still fires.
document.addEventListener('pointerdown', (e) => { if (e.target.closest('button')) e.preventDefault(); });

// Feedback: vibration and a short beep, so the operator knows without looking
let audio;
function feedback(ok) {
  try { navigator.vibrate && navigator.vibrate(ok ? 60 : [80, 60, 80]); } catch (e) {}
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = ok ? 880 : 220; g.gain.value = .08;
    o.connect(g); g.connect(audio.destination); o.start(); o.stop(audio.currentTime + (ok ? .09 : .25));
  } catch (e) {}
}
let hideMsg;
function show(text, ok) {
  feedback(ok);
  const m = $('msg'); m.textContent = text; m.className = 'msg ' + (ok ? 'ok' : 'err');
  clearTimeout(hideMsg);
  hideMsg = setTimeout(() => { m.className = 'msg'; }, ok ? 3500 : 7000);
}
// Start (Fila): the MO goes to every work center. Fechar MO (Em curso): two taps, the first arms it.
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-start], [data-close]');
  if (!btn || btn.disabled) return;
  if (btn.dataset.close && !btn.classList.contains('armed')) {
    btn.classList.add('armed'); btn.classList.add('danger'); btn.textContent = 'Confirmar fecho?';
    setTimeout(() => { if (btn.isConnected) { btn.classList.remove('armed', 'danger'); btn.textContent = 'Fechar MO'; } }, 4000);
    return;
  }
  btn.disabled = true;
  try {
    const r = btn.dataset.start
      ? await call('/nordwire/pda/assign_mo', {mo_name: btn.dataset.start, workcenter_id: 'all'})
      : await call('/nordwire/pda/close_mo', {mo_name: btn.dataset.close});
    show(r.message, r.success);
  } catch (err) { show(err.message, false); }
  btn.disabled = false;
  refreshTodo(); loadWorkcenters();
});
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.notok');
  if (!btn || btn.disabled) return;
  btn.disabled = true;
  try {
    const r = await call('/nordwire/pda/not_ok', {mo_name: btn.dataset.mo});
    show(r.message, r.success);
  } catch (err) { show(err.message, false); }
  btn.disabled = false;
  refreshTodo();
});
let wcs = [], selectedWc = 'all';
try { selectedWc = localStorage.getItem('pda_wc') || 'all'; } catch (e) {}
function renderWc() {
  const sel = selectedWc === 'all' ? null : wcs.find((w) => String(w.id) === String(selectedWc));
  if (!sel) selectedWc = 'all';
  const btn = (id, name, sub, cls) => `<button type="button" class="wcb ${cls}${String(selectedWc) === String(id) ? ' on' : ''}" data-wc="${id}"><b>${esc(name)}</b><small>${sub}</small></button>`;
  $('wc-grid').innerHTML = btn('all', 'Todas as máquinas', `${wcs.length} postos`, 'all') +
    wcs.map((w) => btn(w.id, w.name, w.current_mo ? esc(w.current_mo) : 'livre', '')).join('');
  const chip = $('wc-chip');
  chip.innerHTML = `Posto: ${esc(sel ? sel.name : 'Todas as máquinas')}<small>mudar</small>`;
  chip.hidden = current === 'home';
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-wc]');
  if (!b) return;
  selectedWc = b.dataset.wc;
  try { localStorage.setItem('pda_wc', selectedWc); } catch (e2) {}
  renderWc();
  const w = wcs.find((x) => String(x.id) === selectedWc);
  show(w ? 'Posto: ' + w.name : 'Todas as máquinas', true);
});
async function loadWorkcenters() {
  try { wcs = await call('/nordwire/pda/workcenters_list', {}); } catch (e) { return; }
  renderWc();
}
// A scan is the setup: no confirm step. The field is cleared at once so the next scan can come in.
async function setup() {
  const mo = code.value.trim();
  code.value = ''; code.focus();
  if (!mo) return;
  try {
    const r = current === 'deliver'
      ? await call('/nordwire/pda/deliver_scan', {mo_name: mo})
      : await call('/nordwire/pda/assign_mo', {mo_name: mo, workcenter_id: selectedWc});
    show(r.message, r.success);
  } catch (e) { show(e.message, false); }
  refreshTodo(); loadWorkcenters();
}
code.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); setup(); } });
const focusScan = () => { const a = document.activeElement; if (!a || a.id !== 'qty') code.focus(); };
code.addEventListener('blur', () => setTimeout(focusScan, 0));
document.addEventListener('focusout', () => setTimeout(focusScan, 0));
document.addEventListener('click', focusScan);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { focusScan(); refreshTodo(); } });
window.addEventListener('focus', focusScan);
// "Ler" button: camera through BarcodeDetector where the browser offers it (needs
// https or localhost); else it just arms the field for the PDA's hardware trigger
let stream = null, scanning = false;
function stopCam() { scanning = false; if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; $('cam').hidden = true; $('camclose').classList.remove('on'); code.focus(); }
async function readQr() {
  code.focus();
  if (!('BarcodeDetector' in window) || !navigator.mediaDevices || !window.isSecureContext) {
    show('Aponte o leitor ao QR e prima o gatilho.', true); return;
  }
  try {
    const det = new BarcodeDetector({formats: ['qr_code']});
    stream = await navigator.mediaDevices.getUserMedia({video: {facingMode: 'environment'}});
    const v = $('cam'); v.srcObject = stream; v.hidden = false; $('camclose').classList.add('on'); await v.play();
    scanning = true;
    while (scanning) {
      const found = await det.detect(v).catch(() => []);
      if (found.length) { code.value = found[0].rawValue; stopCam(); setup(); return; }
      await new Promise((r) => setTimeout(r, 200));
    }
  } catch (e) { stopCam(); show('Câmara indisponível: ' + e.message, false); }
}
$('read').addEventListener('click', readQr);
$('camclose').addEventListener('click', stopCam);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('/nordwire/pda-sw.js', {scope: '/nordwire/'}).catch(() => {});
showScreen(); loadWorkcenters();
setInterval(() => { refreshTodo(); loadWorkcenters(); }, 15000);
</script>
</body>
</html>
"""


_SERVICE_WORKER = '''const OFFLINE = '<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Nord PDA</title><body style="font-family:sans-serif;background:#112138;color:#fff;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;text-align:center"><div><h2>Sem ligação</h2><p>Verifique o Wi-Fi e tente de novo.</p><button onclick="location.reload()" style="font-size:18px;padding:12px 24px;border-radius:10px;border:0">Tentar de novo</button></div>';
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  if (e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).catch(() => new Response(OFFLINE, {headers: {'Content-Type': 'text/html; charset=utf-8'}})));
  }
});
'''


class NordSyncPda(Controller):

    def _env(self):
        """The PDA's calls carry no context, so the session's language is
        the browser's: run them in the operator's own, which is what the
        notes they leave on the MO are written in."""
        return request.env(context=dict(request.env.context, lang=request.env.user.lang))

    @route('/nordwire/pda.webmanifest', type='http', auth='public', methods=['GET'])
    def pda_manifest(self, **kwargs):
        """Installable app: opens straight on the PDA page, standalone."""
        manifest = {
            'name': 'Nord PDA',
            'short_name': 'Nord PDA',
            'description': 'Chão de fábrica Nordwire',
            'start_url': '/nordwire/pda',
            'scope': '/nordwire/',
            'id': '/nordwire/pda',
            'display': 'standalone',
            'orientation': 'portrait',
            'background_color': '#112138',
            'theme_color': '#112138',
            'lang': 'pt',
            'icons': [
                {'src': '/nord_sync_mrp/static/src/img/pda-192.png', 'sizes': '192x192', 'type': 'image/png', 'purpose': 'any maskable'},
                {'src': '/nord_sync_mrp/static/src/img/pda-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'any maskable'},
            ],
        }
        return request.make_response(json.dumps(manifest), headers=[('Content-Type', 'application/manifest+json')])

    @route('/nordwire/pda-sw.js', type='http', auth='public', methods=['GET'])
    def pda_service_worker(self, **kwargs):
        """Minimal service worker (what makes the page installable): the
        network is always used, a small offline notice replaces the browser's
        error page."""
        return request.make_response(_SERVICE_WORKER, headers=[
            ('Content-Type', 'application/javascript; charset=utf-8'),
            ('Service-Worker-Allowed', '/nordwire/'),
            ('Cache-Control', 'no-cache'),
        ])

    @route(['/nordwire/pda', '/nord_sync/pda'], type='http', auth='user', methods=['GET'])
    def pda_page(self, **kwargs):
        return request.make_response(_PAGE, headers=[('Content-Type', 'text/html; charset=utf-8')])

    @route('/nordwire/pda/todo', type='jsonrpc', auth='user', methods=['POST'])
    def pda_todo(self, **kwargs):
        """The MOs still to do, grouped by the work center of the operation
        each one is waiting for (its next open work order, the one a scan
        sets up). A work center with nothing waiting is left out."""
        productions = self._env()['mrp.production'].search([
            ('state', 'in', ('confirmed', 'progress', 'to_close')),
            ('company_id', 'in', request.env.companies.ids),
        ], order='id', limit=200)
        # MOs selected on a work center (what a scan sets) and where
        selected = {}
        for wc in self._env()['mrp.workcenter'].search([
            ('company_id', 'in', request.env.companies.ids), ('nord_sync_current_production_id', '!=', False),
        ]):
            selected.setdefault(wc.nord_sync_current_production_id.id, []).append(wc.display_name or wc.name)
        groups = {}
        for production in productions:
            workorder = production.workorder_ids.filtered(
                lambda wo: wo.state not in ('done', 'cancel')
            ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
            if not workorder:
                continue
            # The operation a machine is running on wins over the next open one:
            # that is the one Não OK counts on
            running_wo = production.workorder_ids.filtered(
                lambda wo: wo.state == 'progress' and wo._nord_sync_is_running()
            ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
            workorder = running_wo or workorder
            group = groups.setdefault(workorder.workcenter_id.id, {
                'workcenter': workorder.workcenter_id.display_name,
                'sequence': workorder.workcenter_id.sequence,
                'orders': [],
            })
            running = workorder.state == 'progress' and workorder._nord_sync_is_running()
            open_kinds = set(workorder.time_ids.filtered(lambda t: not t.date_end).mapped('nord_sync_downtime_kind'))
            if running:
                floor = 'running'
            elif 'setup' in open_kinds:
                floor = 'setup'
            elif workorder.state == 'progress':
                floor = 'stopped'
            else:
                floor = ''
            sale_name = production._nord_sync_sale().name
            group['orders'].append({
                'id': production.id,
                'selected_wc': ', '.join(selected.get(production.id, [])),
                'sale': sale_name or production.origin or '',
                'name': production.name,
                'product': production.product_id.display_name,
                'qty': f'{production.product_qty:g} {production.product_uom_id.name}',
                'operation': workorder.name,
                'in_progress': workorder.state == 'progress',
                # The machine on this operation, as Nord's live lines show it
                'floor': floor,
                'running': running,
                'qty_planned': production.product_qty,
                'can_not_ok': running and workorder.workcenter_id.nord_sync_stop_tracking,
                'not_ok': workorder.nord_sync_not_ok_count,
            })
        return [
            {'workcenter': group['workcenter'], 'orders': group['orders']}
            for group in sorted(groups.values(), key=lambda g: (g['sequence'], g['workcenter']))
        ]

    @route('/nordwire/pda/not_ok', type='jsonrpc', auth='user', methods=['POST'])
    def pda_not_ok(self, mo_name, **kwargs):
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        in_progress = production.workorder_ids.filtered(lambda wo: wo.state == 'progress')
        workorder = in_progress.filtered(lambda wo: wo._nord_sync_is_running()).sorted(
            lambda wo: (wo.sequence, wo.id))[:1] or in_progress.sorted(lambda wo: (wo.sequence, wo.id))[:1]
        if not workorder:
            return {'success': False, 'message': f'{mo_name}: nenhuma operação em curso.'}
        try:
            count = workorder.action_nord_sync_not_ok()
            wake_core(request.env)
            webhook(request.env, 'not_ok', {'mo': production.name, 'operation': workorder.name,
                                    'workcenter': workorder.workcenter_id.name, 'count': count})
        except UserError as e:
            return {'success': False, 'message': f'{mo_name}: {e}'}
        return {'success': True, 'message': f'{mo_name}: Não OK registado ({count}).'}

    @route('/nordwire/pda/deliver', type='jsonrpc', auth='user', methods=['POST'])
    def pda_deliver(self, mo_name, qty=None, **kwargs):
        """Delivers and closes the MO with `qty` good units (default: the
        planned quantity), as a Nord "Mark Done" would. Only for an MO running
        on a stop-tracking work center."""
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        try:
            qty = None if qty in (None, '') else float(qty)
        except ValueError:
            return {'success': False, 'message': f'{mo_name}: quantidade inválida.'}
        if qty is not None and qty < 0:
            return {'success': False, 'message': f'{mo_name}: quantidade inválida.'}
        success, message = production._nord_sync_demo_deliver(qty=qty)
        if success:
            wake_core(request.env)
            webhook(request.env, 'deliver', {'mo': production.name, 'state': production.state, 'qty': qty})
        return {'success': success, 'message': message}

    @route('/nordwire/pda/deliveries', type='jsonrpc', auth='user', methods=['POST'])
    def pda_deliveries(self, **kwargs):
        """Entrega list: the closed MOs whose delivery is still open."""
        out = []
        for production in self._env()['mrp.production'].search([
            ('state', '=', 'done'), ('company_id', 'in', request.env.companies.ids),
        ], order='id desc', limit=100):
            picking = production._nord_sync_find_delivery(create=False)
            if not picking:
                continue
            out.append({
                'name': production.name,
                'product': production.product_id.display_name,
                'qty': f'{production.product_qty:g} {production.product_uom_id.name}',
                'sale': production._nord_sync_sale().name or production.origin or '',
                'delivery': picking.name,
            })
        return out

    @route('/nordwire/pda/deliver_scan', type='jsonrpc', auth='user', methods=['POST'])
    def pda_deliver_scan(self, mo_name, **kwargs):
        """Entrega mode: the scanned MO's delivery is confirmed, forced."""
        mo_name = (mo_name or '').strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        try:
            success, message = production._nord_sync_force_deliver()
        except UserError as e:
            return {'success': False, 'message': f'{mo_name}: {e}'}
        if success:
            wake_core(request.env)
            webhook(request.env, 'deliver', {'mo': production.name, 'state': production.state})
        return {'success': success, 'message': message}

    @route('/nordwire/pda/close_mo', type='jsonrpc', auth='user', methods=['POST'])
    def pda_close_mo(self, mo_name, **kwargs):
        """Em curso "Fechar MO": closes the MO with its planned quantity."""
        mo_name = (mo_name or '').strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        try:
            success, message = production._nord_sync_force_close()
        except UserError as e:
            return {'success': False, 'message': f'{mo_name}: {e}'}
        if success:
            wake_core(request.env)
            webhook(request.env, 'close_mo', {'mo': production.name, 'state': production.state})
        return {'success': success, 'message': message}

    @route('/nordwire/pda/setup', type='jsonrpc', auth='user', methods=['POST'])
    def pda_setup(self, mo_name, **kwargs):
        mo_name = mo_name.strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}
        # The operation the MO is waiting for: work orders come in sequence
        workorder = production.workorder_ids.filtered(
            lambda wo: wo.state not in ('done', 'cancel')
        ).sorted(lambda wo: (wo.sequence, wo.id))[:1]
        if not workorder:
            return {'success': False, 'message': f'{mo_name}: nada por fazer.'}
        workorder._nord_sync_notify_floor_event('setup')
        wake_core(request.env)
        webhook(request.env, 'pda_setup', {'mo': production.name, 'operation': workorder.name,
                                                   'workcenter': workorder.workcenter_id.name})
        production._nord_sync_ensure_delivery()
        # The Core makes a second scan of the same MO on the same work center
        # a plain selection (no new setup), so say so instead of "setup".
        params = request.env['ir.config_parameter'].sudo()
        key = f'nord_sync.pda_selected.{workorder.workcenter_id.id}'
        selected_again = params.get_param(key) == str(production.id)
        params.set_param(key, production.id)
        # The Core keeps a scan made while the machine runs another MO
        # pending until that run stops: the next start is this MO's.
        # The latest open work line is the machine's run: an older one left
        # open (a session never closed) isn't what is on the machine now.
        line = self._env()['mrp.workcenter.productivity'].search([
            ('workcenter_id', '=', workorder.workcenter_id.id), ('date_end', '=', False),
            ('nord_sync_downtime_kind', '=', False), ('workorder_id.state', '=', 'progress'),
        ], order='date_start desc, id desc', limit=1)
        running = line.workorder_id if line.workorder_id != workorder else self._env()['mrp.workorder']
        if running:
            message = (f'{mo_name} pendente em {workorder.workcenter_id.name}: '
                       f'{running.production_id.name} continua até a máquina parar.')
        elif selected_again:
            message = f'{mo_name} selecionada em {workorder.workcenter_id.name}.'
        else:
            message = f'{mo_name} em setup em {workorder.workcenter_id.name}.'
        return {'success': True, 'message': message, 'selected_again': selected_again,
                'pending': bool(running)}

    @route('/nordwire/pda/workcenters_list', type='jsonrpc', auth='user', methods=['POST'])
    def pda_workcenters_list(self, **kwargs):
        workcenters = self._env()['mrp.workcenter'].search([
            ('company_id', 'in', request.env.companies.ids),
        ], order='sequence, name')
        return [
            {
                'id': wc.id,
                'name': wc.display_name or wc.name,
                'current_mo': wc.nord_sync_current_production_id.name or False,
            }
            for wc in workcenters
        ]

    @route('/nordwire/pda/assign_mo', type='jsonrpc', auth='user', methods=['POST'])
    def pda_assign_mo(self, mo_name, workcenter_id='all', **kwargs):
        mo_name = (mo_name or '').strip()
        production = self._env()['mrp.production'].search([
            ('name', '=', mo_name), ('company_id', 'in', request.env.companies.ids),
        ], limit=1)
        if not production:
            return {'success': False, 'message': f'{mo_name}: MO não encontrada.'}

        Workcenter = self._env()['mrp.workcenter']
        if workcenter_id == 'all':
            workcenters = Workcenter.search([
                ('company_id', 'in', request.env.companies.ids),
            ])
            if not workcenters:
                return {'success': False, 'message': 'Nenhum posto de trabalho encontrado.'}
        else:
            try:
                wc_id = int(workcenter_id)
                workcenters = Workcenter.browse(wc_id)
                if not workcenters.exists():
                    return {'success': False, 'message': 'Posto de trabalho não encontrado.'}
            except (ValueError, TypeError):
                return {'success': False, 'message': 'Identificador de posto inválido.'}

        updated_names = []
        errors = []
        for wc in workcenters:
            try:
                wc.nord_sync_current_production_id = production.id
                updated_names.append(wc.display_name or wc.name)
            except UserError as ue:
                errors.append(f"{wc.name}: {ue.args[0]}")
            except Exception as e:
                errors.append(f"{wc.name}: {e}")

        wake_core(request.env)
        webhook(request.env, 'pda_assign_mo', {
            'mo': production.name,
            'workcenters': [w.name for w in workcenters],
            'updated': updated_names,
            'errors': errors,
        })

        if errors and not updated_names:
            return {'success': False, 'message': ' | '.join(errors)}
        elif errors:
            return {
                'success': True,
                'message': f"{mo_name} atribuída a: {', '.join(updated_names)}. Avisos: {' | '.join(errors)}",
            }
        else:
            if workcenter_id == 'all':
                return {'success': True, 'message': f"{mo_name} atribuída a todas as máquinas ({len(updated_names)})."}
            return {'success': True, 'message': f"{mo_name} atribuída a {updated_names[0]}."}

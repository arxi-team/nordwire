/** @odoo-module **/

import { Component, onWillDestroy, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

// ponytail: plain polling, not a bus/websocket push — the count changes at most
// once per cron tick (5 min, Slice 4.3) or a manual retry, so a 30s poll is
// already far more responsive than that, without wiring real-time infra for a
// low-frequency number. Upgrade to a bus notification if that ever isn't enough.
const POLL_INTERVAL_MS = 30000;

/**
 * Docs/NordSyncFase2, Fase 4 Slice 4.1 — permanent failure-count indicator,
 * inspired by custom/integration's IntegrationStatusMenu (same registry,
 * same "one number, click to see detail" shape) but simplified: a single
 * count (no per-integration breakdown, no missing-mappings concept — Slice
 * 2.2/2.3 already auto-resolve those from the payload, see
 * custom/plano_addon_odoo_cliente_producao.md §7), and a click navigates
 * straight to the dedicated failures list (Slice 4.2) instead of opening an
 * in-place dropdown panel.
 */
export class NordSyncSystray extends Component {
    static template = "nord_sync.NordSyncSystray";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.state = useState({ failedCount: 0 });
        onWillStart(() => this._fetchFailedCount());

        const intervalId = setInterval(() => this._fetchFailedCount(), POLL_INTERVAL_MS);
        onWillDestroy(() => clearInterval(intervalId));
    }

    async _fetchFailedCount() {
        this.state.failedCount = await this.orm.call(
            "nord.sync.queue",
            "systray_get_failed_count",
            [],
        );
    }

    onClick() {
        this.actionService.doAction("nord_sync.action_nord_sync_failures");
    }
}

registry.category("systray").add(
    "nord_sync.NordSyncSystray",
    { Component: NordSyncSystray },
    { sequence: 25 },
);

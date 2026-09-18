/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * "Sync Overview" — read-only snapshot of nord.sync.queue and
 * nord_sync.inbox for the current company: a KPI cards row plus three
 * breakdown panels (outbound queue, inbound inbox, current failures). No
 * date range, no percent-vs-previous-period, no server-side
 * cache — the queue itself is a 2h-retention transient model, so there is
 * nothing to compare against and nothing worth caching; a Refresh button is
 * enough, no auto-polling needed at this volume.
 */
// Same status set as nord.sync.queue/nord_sync.inbox's own selections — one
// badge color per status, shared by every table in this dashboard so
// "failed" always reads the same regardless of which panel it's in.
const STATUS_BADGE_CLASS = {
    pending: "text-bg-secondary",
    sent: "text-bg-success",
    done: "text-bg-success",
    failed: "text-bg-danger",
};

export class SyncOverview extends Component {
    static template = "nord_sync.SyncOverview";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            kpis: { pending: 0, sent: 0, failed: 0, unsealed: 0 },
            queue: [],
            inbox: [],
            failures: [],
        });
        onWillStart(() => this._fetchData());
    }

    async _fetchData() {
        this.state.loading = true;
        const data = await this.orm.call("nord.sync.queue", "get_overview_data", []);
        this.state.kpis = data.kpis;
        this.state.queue = data.queue;
        this.state.inbox = data.inbox;
        this.state.failures = data.failures;
        this.state.loading = false;
    }

    statusBadgeClass(status) {
        return STATUS_BADGE_CLASS[status] || "text-bg-secondary";
    }

    async onRefresh() {
        await this._fetchData();
    }

    onOpenQueue() {
        this.action.doAction("nord_sync.action_nord_sync_queue");
    }

    onOpenFailures() {
        this.action.doAction("nord_sync.action_nord_sync_failures");
    }

    onOpenInbox() {
        this.action.doAction("nord_sync.action_nord_sync_inbox");
    }

    // Pending/sent/unsealed all live on the same nord.sync.queue list, so
    // clicking any of those 3 KPI cards opens it too, filtered to just that
    // slice (not the full queue the header button opens) — only "failed"
    // has a dedicated screen already filtered server-side.
    async onKpiClick(kind) {
        if (kind === "failed") {
            return this.onOpenFailures();
        }
        const kwargs = kind === "unsealed" ? { unsealed: true } : { status: kind };
        const action = await this.orm.call(
            "nord.sync.queue", "action_open_queue_filtered", [], kwargs,
        );
        this.action.doAction(action);
    }
}

registry.category("actions").add("nord_sync_sync_overview", SyncOverview);

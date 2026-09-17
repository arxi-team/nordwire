/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

/**
 * "Sync Overview" — read-only snapshot of nord.sync.queue for the current
 * company: a KPI cards row plus two breakdown panels (by model, current
 * failures). No date range, no percent-vs-previous-period, no server-side
 * cache — the queue itself is a 2h-retention transient model, so there is
 * nothing to compare against and nothing worth caching; a Refresh button is
 * enough, no auto-polling needed at this volume.
 */
export class SyncOverview extends Component {
    static template = "nord_sync.SyncOverview";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            kpis: { pending: 0, sent: 0, failed: 0, unsealed: 0 },
            byModel: [],
            failures: [],
        });
        onWillStart(() => this._fetchData());
    }

    async _fetchData() {
        const data = await this.orm.call("nord.sync.queue", "get_overview_data", []);
        this.state.kpis = data.kpis;
        this.state.byModel = data.by_model;
        this.state.failures = data.failures;
    }

    async onRefresh() {
        await this._fetchData();
    }
}

registry.category("actions").add("nord_sync_sync_overview", SyncOverview);

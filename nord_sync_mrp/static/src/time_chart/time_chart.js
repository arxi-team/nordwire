import { Component, onWillStart, status, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Same meaning on the PDA, the list decorations and here: green works, red
// stops, amber is setup, purple is quality. Offline (inside the work day, no
// signal) and outside the work day follow the Core's greys; productive time
// outside the work day is painted light blue.
const COLORS = {
    productive: "#28a745",
    stop: "#dc3545",
    setup: "#f0ad4e",
    quality: "#6f42c1",
    offline: "#adb5bd",
    outside: "#dee1e5",
    overtime: "#74c0fc",
};

/**
 * Today (one cell per hour of its work day), the week or the month (one cell
 * per day) of a work center on its Nordwire tab, painted by the share of each state (the Core's analytics timeline).
 * Lives on a placeholder field (mrp.workcenter.nord_sync_time_chart) and
 * fetches its own data, so it follows the Core's sessions as they are logged
 * without saving the form.
 */
export class NordSyncTimeChart extends Component {
    static template = "nord_sync_mrp.NordSyncTimeChart";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, period: "today" });
        onWillStart(() => this.load());
    }

    async load() {
        if (!this.props.record.resId || status(this) === "destroyed") {
            return;
        }
        this.state.data = await this.orm.call(
            "mrp.workcenter",
            "nord_sync_time_chart_data",
            [this.props.record.resId, this.state.period]
        );
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }

    get periods() {
        return [
            { key: "today", label: _t("Today") },
            { key: "week", label: _t("Week") },
            { key: "month", label: _t("Month") },
        ];
    }

    get legend() {
        const labels = {
            productive: _t("Running"),
            stop: _t("Downtime"),
            setup: _t("Setup"),
            quality: _t("Quality"),
            offline: _t("Offline"),
            outside: _t("Outside calendar"),
            overtime: _t("Overtime"),
        };
        return Object.keys(labels).map((key) => ({ key, label: labels[key], color: COLORS[key] }));
    }

    get totals() {
        const labels = Object.fromEntries(this.legend.map((item) => [item.key, item.label]));
        return this.state.data.categories.map((c) => ({
            key: c.key,
            label: labels[c.key],
            color: COLORS[c.key],
            minutes: this.state.data.totals[c.key],
        }));
    }

    /** Axis thinning of the Core: every label up to 12 cells, else every 5th and the last. */
    get axisLabels() {
        const labels = this.state.data.buckets.map((b) => b.label);
        return labels.length <= 12
            ? labels
            : labels.filter((_label, i) => i % 5 === 0 || i === labels.length - 1);
    }

    labelOf(key) {
        return this.legend.find((item) => item.key === key)?.label || key;
    }

    /** The parts of a cell, biggest share first isn't wanted: fixed order, bottom-up. */
    parts(bucket) {
        const total = this.elapsed(bucket);
        return this.legend
            .filter((item) => bucket.minutes[item.key] > 0)
            .map((item) => ({
                key: item.key,
                color: item.color,
                minutes: bucket.minutes[item.key],
                pct: (bucket.minutes[item.key] / total) * 100,
            }));
    }

    elapsed(bucket) {
        return Object.values(bucket.minutes).reduce((a, b) => a + b, 0) || 1;
    }

    cellTitle(bucket) {
        if (bucket.future) {
            return `${bucket.label} · ${_t("to come")}`;
        }
        const detail = this.parts(bucket)
            .sort((a, b) => b.minutes - a.minutes)
            .map((part) => `${this.labelOf(part.key)} ${this.formatHM(part.minutes)}`)
            .join(" · ");
        return `${bucket.label} · ${detail || _t("no activity")}`;
    }

    formatHM(minutes) {
        const total = Math.round(minutes);
        return `${String(Math.floor(total / 60)).padStart(2, "0")}:${String(total % 60).padStart(2, "0")}`;
    }

    formatMinutes(minutes) {
        const hours = Math.floor(minutes / 60);
        const rest = Math.round(minutes % 60);
        return hours ? `${hours}h${String(rest).padStart(2, "0")}` : `${rest} min`;
    }

    async openDetails() {
        const action = await this.orm.call(
            "mrp.workcenter",
            "action_nord_sync_time_report",
            [this.props.record.resId]
        );
        await this.action.doAction(action);
    }
}

registry.category("fields").add("nord_sync_time_chart", {
    component: NordSyncTimeChart,
});

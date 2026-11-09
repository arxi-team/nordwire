import { Component, onWillStart, onWillUnmount, status, useEffect, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// The machine screen of Kioda: availability amber, performance red, quality
// green; the working hours in blues by how much of the 15 minutes ran.
const COLORS = {
    availability: "#f4d03f",
    performance: "#dc2828",
    quality: "#28b463",
    good: "#2eb88a",
    bad: "#dc2828",
    oee: "#1d4ed8",
    average: "rgba(120, 120, 120, 0.9)",
};

/**
 * Today of a work center as the Kioda machine screen shows a machine: the
 * OEE header (OEE against its target, availability / performance / quality,
 * work time, production and quality cards), the working hours timeline (one
 * segment per 15 minutes), the declarations per hour and the OEE per hour.
 * Lives on a placeholder field (mrp.workcenter.nord_sync_machine_overview)
 * and fetches its own data in one call (nord_sync_machine_overview_data).
 */
export class NordSyncMachineOverview extends Component {
    static template = "nord_sync_mrp.NordSyncMachineOverview";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: false, allAlerts: false, tip: null });
        this.declarationsRef = useRef("declarations");
        this.oeeRef = useRef("oeeByHour");
        this.charts = [];
        onWillStart(() => loadBundle("web.chartjs_lib"));
        // Entering the work center (and moving to another one with the pager)
        // runs the Refresh by itself
        useEffect(
            () => {
                this.state.tip = null;
                this.load();
            },
            () => [this.props.record.resId]
        );
        useEffect(
            () => this.renderCharts(),
            () => [this.state.data]
        );
        onWillUnmount(() => this.destroyCharts());
    }

    async load() {
        // The chart bundle is awaited before this runs: the form may be left (a
        // quick tab change, a save) meanwhile, and the ORM refuses to be called
        // from a destroyed component, which showed the generic error dialog
        // instead of the real one of whatever the user was doing.
        if (!this.props.record.resId || status(this) === "destroyed") {
            return;
        }
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "mrp.workcenter",
                "nord_sync_machine_overview_data",
                [this.props.record.resId]
            );
        } finally {
            this.state.loading = false;
        }
    }

    // ── OEE header ────────────────────────────────────────────────────────

    get factors() {
        const oee = this.state.data.oee;
        return [
            { key: "availability", label: _t("Availability"), value: oee.availability },
            {
                key: "performance",
                label: _t("Performance"),
                value: oee.performance,
                // Above 100% the pace beats the capacity per hour: the OEE counts it as 100%
                over: oee.performance > 100,
            },
            { key: "quality", label: _t("Quality"), value: oee.quality },
        ];
    }

    clamp(value) {
        return Math.max(0, Math.min(100, value || 0));
    }

    donutStyle(factor) {
        const pct = this.clamp(factor.value);
        return `background: conic-gradient(${COLORS[factor.key]} 0 ${pct}%, var(--o-nord-overview-track) ${pct}% 100%)`;
    }

    formatPct(value) {
        return `${Math.round(value || 0)}%`;
    }

    formatQty(value) {
        return Number.isInteger(value) ? String(value) : (value || 0).toFixed(1);
    }

    formatHours(hours) {
        const minutes = Math.round((hours || 0) * 60);
        return `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
    }

    formatMinutes(minutes) {
        return this.formatHours((minutes || 0) / 60);
    }

    progress(real, planned) {
        return planned ? this.clamp((real / planned) * 100) : 0;
    }

    get capacityNote() {
        const oee = this.state.data.oee;
        if (oee.capacity_source === "workcenter") {
            return _t("%s per hour", this.formatQty(oee.capacity_per_hour));
        }
        if (oee.capacity_source === "fallback") {
            return _t("%s per hour, fallback capacity", this.formatQty(oee.capacity_per_hour));
        }
        if (oee.capacity_source === "workorders") {
            return _t("%s per hour, estimated from today's work orders", this.formatQty(oee.capacity_per_hour));
        }
        return _t("No capacity per hour set: performance not measured");
    }

    // ── Working hours ─────────────────────────────────────────────────────

    get states() {
        return [
            { key: "working", label: _t("Working"), css: "working_90" },
            { key: "setup", label: _t("Setup"), css: "setup" },
            { key: "idle", label: _t("Idle"), css: "idle" },
            { key: "offline", label: _t("Offline"), css: "offline" },
        ];
    }

    get statusLabel() {
        const status = this.state.data.utilization.current_status;
        return this.states.find((s) => s.key === status)?.label || status;
    }

    /** The hover popup of a 15 minute segment, placed on the bar (above it, below near the top). */
    showTip(ev, segment) {
        const rect = ev.currentTarget.getBoundingClientRect();
        const width = 250;
        const below = rect.top < 230;
        this.state.tip = {
            segment,
            below,
            x: Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2)),
            y: below ? rect.bottom + 10 : rect.top - 10,
            arrow: Math.max(14, Math.min(width - 14, rect.left + rect.width / 2 - Math.max(8, Math.min(window.innerWidth - width - 8, rect.left + rect.width / 2 - width / 2)))),
        };
    }

    hideTip() {
        this.state.tip = null;
    }

    tipStatus(segment) {
        if (segment.status === "future") {
            return { label: _t("To come"), css: "future" };
        }
        const key = segment.status.startsWith("working") ? "working" : segment.status;
        return { label: this.states.find((s) => s.key === key)?.label || key, css: key };
    }

    tipRows(segment) {
        const total = Math.max(15, ...this.states.map((s) => segment.minutes[s.key] || 0));
        return this.states
            .filter((s) => segment.minutes[s.key])
            .map((s) => ({
                key: s.key,
                label: s.label,
                minutes: segment.minutes[s.key],
                pct: this.clamp((segment.minutes[s.key] / total) * 100),
            }));
    }

    segmentTitle(segment) {
        if (segment.status === "future") {
            return `${segment.label} · ${_t("to come")}`;
        }
        const detail = this.states
            .filter((s) => segment.minutes[s.key])
            .map((s) => `${s.label} ${segment.minutes[s.key]} min`)
            .join(" · ");
        const alarm = segment.minutes.alarm ? ` · ${_t("Alarm")} ${segment.minutes.alarm} min` : "";
        return `${segment.label} · ${detail}${alarm}`;
    }

    get axisLabels() {
        return ["00:00", "06:00", "12:00", "18:00", "23:59"];
    }

    // ── Alerts ────────────────────────────────────────────────────────────

    /** The open alerts and the latest closed ones, all of them on demand. */
    get alertItems() {
        const items = this.state.data.alerts.items;
        return this.state.allAlerts ? items : items.slice(0, Math.max(5, this.state.data.alerts.open));
    }

    async openAlerts() {
        const action = await this.orm.call(
            "mrp.workcenter",
            "action_nord_sync_alerts",
            [this.props.record.resId]
        );
        await this.action.doAction(action);
    }

    // ── Charts ────────────────────────────────────────────────────────────

    destroyCharts() {
        for (const chart of this.charts) {
            chart.destroy();
        }
        this.charts = [];
    }

    chartOptions({ stacked = false, max = undefined } = {}) {
        const tick = { color: "#8a8f98", font: { weight: "bold" } };
        return {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: "index", intersect: false },
            plugins: { legend: { display: true, position: "top" } },
            scales: {
                x: { stacked, grid: { display: false }, ticks: tick },
                y: { stacked, beginAtZero: true, max, grid: { color: "rgba(128, 128, 128, 0.2)" }, ticks: tick },
            },
        };
    }

    averageLine(label, value, length) {
        return {
            label,
            type: "line",
            data: Array(length).fill(value),
            borderColor: COLORS.average,
            borderWidth: 2,
            borderDash: [5, 5],
            pointRadius: 0,
            fill: false,
            order: 0,
        };
    }

    renderCharts() {
        this.destroyCharts();
        const data = this.state.data;
        if (!data || !window.Chart || !this.declarationsRef.el || !this.oeeRef.el) {
            return;
        }
        const top = { topLeft: 4, topRight: 4, bottomLeft: 0, bottomRight: 0 };

        const declarations = data.declarations.hours;
        const labels = declarations.map((h) => h.label);
        this.charts.push(
            new window.Chart(this.declarationsRef.el, {
                type: "bar",
                data: {
                    labels,
                    datasets: [
                        this.averageLine(_t("Average good"), data.declarations.average_good, labels.length),
                        {
                            label: _t("Good"),
                            data: declarations.map((h) => h.good),
                            backgroundColor: COLORS.good,
                            borderRadius: declarations.map((h) => (h.bad ? 0 : top)),
                            borderSkipped: false,
                            order: 1,
                        },
                        {
                            label: _t("Bad"),
                            data: declarations.map((h) => h.bad),
                            backgroundColor: COLORS.bad,
                            borderRadius: top,
                            borderSkipped: false,
                            order: 1,
                        },
                    ],
                },
                options: this.chartOptions({ stacked: true }),
            })
        );

        const oeeHours = data.oee_by_hour.hours;
        this.charts.push(
            new window.Chart(this.oeeRef.el, {
                type: "bar",
                data: {
                    labels: oeeHours.map((h) => h.label),
                    datasets: [
                        this.averageLine(_t("Average OEE"), data.oee_by_hour.average_oee, oeeHours.length),
                        {
                            label: _t("OEE (%)"),
                            data: oeeHours.map((h) => h.oee),
                            backgroundColor: COLORS.oee,
                            borderRadius: top,
                            borderSkipped: false,
                            order: 1,
                        },
                    ],
                },
                options: {
                    ...this.chartOptions({ max: 100 }),
                    plugins: {
                        legend: { display: true, position: "top" },
                        tooltip: {
                            callbacks: {
                                afterBody: (items) => {
                                    const hour = oeeHours[items[0].dataIndex];
                                    return [
                                        `${_t("Availability")}: ${this.formatPct(hour.availability)}`,
                                        `${_t("Performance")}: ${this.formatPct(hour.performance)}`,
                                        `${_t("Quality")}: ${this.formatPct(hour.quality)}`,
                                    ];
                                },
                            },
                        },
                    },
                },
            })
        );
    }
}

registry.category("fields").add("nord_sync_machine_overview", {
    component: NordSyncMachineOverview,
});

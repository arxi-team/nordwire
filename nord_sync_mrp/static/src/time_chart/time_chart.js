import { Component, onMounted, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { loadBundle } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

// Same meaning on the PDA, the list decorations and here: green works, red
// stops, amber is setup, purple is quality.
const COLORS = {
    productive: "#28a745",
    stop: "#dc3545",
    setup: "#f0ad4e",
    quality: "#6f42c1",
};

const HOVER_COLORS = {
    productive: "#1e7e34",
    stop: "#a71d2a",
    setup: "#c77c0e",
    quality: "#4e2d8a",
};

/**
 * Today's productive / stop / setup / quality time of a work center, per
 * hour, on its Nordwire tab. Lives on a placeholder field
 * (mrp.workcenter.nord_sync_time_chart) and fetches its own data, so it
 * follows the Core's sessions as they are logged without saving the form.
 */
export class NordSyncTimeChart extends Component {
    static template = "nord_sync_mrp.NordSyncTimeChart";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.canvasRef = useRef("canvas");
        this.chart = null;
        this.state = useState({ data: null });
        onWillStart(async () => {
            await loadBundle("web.chartjs_lib");
            await this.load();
        });
        onMounted(() => this.renderChart());
        onWillUnmount(() => this.chart?.destroy());
    }

    async load() {
        if (!this.props.record.resId) {
            return;
        }
        this.state.data = await this.orm.call(
            "mrp.workcenter",
            "nord_sync_time_chart_data",
            [this.props.record.resId]
        );
    }

    async refresh() {
        await this.load();
        this.renderChart();
    }

    totals() {
        const data = this.state.data;
        return data.series.map((serie) => ({
            key: serie.key,
            label: serie.label,
            color: COLORS[serie.key],
            minutes: data.totals[serie.key],
        }));
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

    renderChart() {
        const data = this.state.data;
        if (!data || !this.canvasRef.el) {
            return;
        }
        this.chart?.destroy();
        // Same look as the Kioda resource charts ("by hour" bars): grey bold
        // ticks, horizontal grid only, bold legend on top, darker colour on
        // hover, rounded top corner on the highest bar of each stack and a
        // dashed average line.
        const series = data.series;
        const hourTotals = data.labels.map((_label, i) =>
            series.reduce((sum, serie) => sum + serie.minutes[i], 0)
        );
        const average = hourTotals.length
            ? hourTotals.reduce((a, b) => a + b, 0) / hourTotals.length
            : 0;
        const topSerie = data.labels.map((_label, i) => {
            for (let s = series.length - 1; s >= 0; s--) {
                if (series[s].minutes[i] > 0) {
                    return s;
                }
            }
            return -1;
        });
        const round = { topLeft: 5, topRight: 5, bottomLeft: 0, bottomRight: 0 };
        const tick = { color: "grey", font: { weight: "bold" } };
        this.chart = new Chart(this.canvasRef.el, {
            type: "bar",
            data: {
                labels: data.labels,
                datasets: [
                    {
                        label: _t("Hourly average"),
                        type: "line",
                        data: data.labels.map(() => average),
                        borderColor: "rgba(50, 50, 50, 0.8)",
                        borderWidth: 2,
                        borderDash: [5, 5],
                        pointRadius: 0,
                        order: 0,
                    },
                    ...series.map((serie, s) => ({
                        label: serie.label,
                        data: serie.minutes,
                        backgroundColor: COLORS[serie.key],
                        hoverBackgroundColor: HOVER_COLORS[serie.key],
                        borderRadius: data.labels.map((_label, i) => (topSerie[i] === s ? round : 0)),
                        borderSkipped: false,
                        order: 1,
                    })),
                ],
            },
            options: {
                maintainAspectRatio: false,
                interaction: { mode: "index", intersect: false },
                scales: {
                    x: { stacked: true, grid: { display: false }, ticks: tick },
                    y: {
                        stacked: true,
                        min: 0,
                        max: 60,
                        grid: { display: true },
                        ticks: { ...tick, stepSize: 15, callback: (value) => `${value} min` },
                    },
                },
                plugins: {
                    legend: { display: true, position: "top", labels: { font: { weight: "bold" } } },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                if (ctx.dataset.type === "line") {
                                    return ` ${ctx.dataset.label}: ${this.formatMinutes(ctx.parsed.y)}`;
                                }
                                const total = hourTotals[ctx.dataIndex] || 1;
                                return ` ${ctx.dataset.label}: ${this.formatMinutes(ctx.parsed.y)} (${Math.round((ctx.parsed.y / total) * 100)}%)`;
                            },
                        },
                    },
                },
            },
        });
    }
}

registry.category("fields").add("nord_sync_time_chart", {
    component: NordSyncTimeChart,
});

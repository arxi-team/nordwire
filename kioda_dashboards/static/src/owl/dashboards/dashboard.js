import { Component, useState, onMounted, onWillUnmount, xml } from "@odoo/owl";

export class Dashboard extends Component {
    static template = xml`
        <t t-name="kioda_dashboards.dashboard-main">
            <div class="kioda-dashboard-test">
                <nav class="kioda-header">
                    <span class="kioda-header-title">KIODA</span>
                </nav>
                <div class="kioda-main-content">
                    <h1 t-esc="state.data.name || 'Kioda Dashboard Test'"/>
                    <p>UUID: <t t-esc="state.data.uuid"/></p>
                    <p>Screen: <t t-esc="state.data.screen"/></p>
                    <p>
                        Ticks: <t t-esc="state.ticks"/>
                        <button class="kioda-btn" t-on-click="incrementTicks">+1</button>
                    </p>
                </div>
                <footer class="kioda-footer">
                    <span class="kioda-footer-text" t-esc="state.data.name || 'Kioda Dashboard Test'"/>
                    <span class="kioda-footer-clock" t-esc="state.now"/>
                </footer>
            </div>
        </t>
    `;
    static props = ["data"];

    setup() {
        this.state = useState({
            data: this.props.data,
            now: new Date().toLocaleTimeString(),
            ticks: 0,
        });

        onMounted(() => {
            this.interval = setInterval(() => {
                this.state.now = new Date().toLocaleTimeString();
            }, 1000);
        });

        onWillUnmount(() => {
            clearInterval(this.interval);
        });
    }

    incrementTicks() {
        this.state.ticks += 1;
    }
}

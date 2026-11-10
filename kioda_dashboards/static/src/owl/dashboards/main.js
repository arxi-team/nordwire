import { mount, whenReady } from "@odoo/owl";
import { Dashboard } from "./dashboard";

whenReady(() => {
    const root = document.getElementById("kioda-dashboard-root");
    if (!root) {
        return;
    }
    mount(Dashboard, document.body, {
        dev: true,
        name: "kioda_dashboards",
        props: {
            data: JSON.parse(root.getAttribute("value")),
        },
    });
});

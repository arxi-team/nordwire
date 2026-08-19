# -*- coding: utf-8 -*-
from . import nord_sync_source
from . import nord_sync_config
from . import sync_queue
from . import nord_sync_job_stage
from . import nord_sync_state_mapping
from . import ir_actions_server
from . import ir_http
from . import res_config_settings

# MRP source (merged from nord_sync_mrp, see Docs/ADR/0014-nord-sync-reunify-single-addon.md)
from . import mrp

# Sale source (merged from nord_sync_sale, see Docs/ADR/0014-nord-sync-reunify-single-addon.md)
from . import sale

# Purchase source (merged from nord_sync_purchase, see Docs/ADR/0014-nord-sync-reunify-single-addon.md)
from . import purchase

# Inventory source (merged from nord_sync_inventory, see Docs/ADR/0014-nord-sync-reunify-single-addon.md)
from . import inventory

# Maintenance source (merged from nord_sync_maintenance, see Docs/ADR/0014-nord-sync-reunify-single-addon.md)
from . import maintenance

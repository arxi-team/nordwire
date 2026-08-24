# -*- coding: utf-8 -*-
from . import nord_sync_source
from . import nord_sync_config
from . import nord_sync_notify_mixin
from . import sync_queue
from . import sync_queue_line
from . import nord_sync_job_stage
from . import nord_sync_state_mapping
from . import ir_actions_server
from . import ir_http
from . import res_config_settings

# MRP source — merged in from what used to be the separate nord_sync_mrp addon
from . import mrp

# Sale source — merged in from what used to be the separate nord_sync_sale addon
from . import sale

# Purchase source — merged in from what used to be the separate nord_sync_purchase addon
from . import purchase

# Inventory source — merged in from what used to be the separate nord_sync_inventory addon
from . import inventory

# Maintenance source — merged in from what used to be the separate nord_sync_maintenance addon
from . import maintenance

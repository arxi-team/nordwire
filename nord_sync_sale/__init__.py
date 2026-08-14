# -*- coding: utf-8 -*-
from . import models


def post_init_hook(env):
    """Announce this source to the Core so it can auto-install its own
    nordos_nord_sync_core_sale counterpart, instead of requiring an
    operator to install it by hand on every client onboarding."""
    for company in env['res.company'].sudo().search([]):
        config = env['nord_sync.config'].sudo()._get_for_company(company)
        if config:
            config._push_source_installed_signal('nord_sync_sale')

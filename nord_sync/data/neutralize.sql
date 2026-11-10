-- Nordwire: a neutralized database (a copy of production) must never talk to
-- the Nord Cloud/Core. Run by `odoo-bin neutralize` (odoo.modules.neutralize).
-- Outbound: sync off, wake webhook has no URL, Nordwire crons stopped.
UPDATE nord_sync_config
   SET enabled = false;

UPDATE ir_config_parameter
   SET value = ''
 WHERE key = 'nord_sync.cloud_base_url';

UPDATE ir_cron
   SET active = false
 WHERE id IN (SELECT res_id FROM ir_model_data WHERE module = 'nord_sync' AND model = 'ir.cron');
-- Inbound: Core -> Odoo API calls are refused in ir_http.py while
-- database.is_neutralized is set.

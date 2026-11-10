-- Nordwire PDA demo (controllers/pda.py): wake_core() falls back to a default
-- URL when the parameter is empty, so point it at a port that refuses at once
-- instead of clearing it. The demo webhook has no default: empty = no POST.
INSERT INTO ir_config_parameter (key, value, create_date, write_date)
VALUES ('nord_sync.demo_core_pull_url', 'http://127.0.0.1:1/neutralized', now(), now())
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;

UPDATE ir_config_parameter
   SET value = ''
 WHERE key = 'nord_sync.demo_webhook_url';

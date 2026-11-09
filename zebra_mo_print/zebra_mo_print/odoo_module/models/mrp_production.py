import logging
import subprocess

from odoo import models

_logger = logging.getLogger(__name__)

SSH_KEY = "/var/odoo/coffeepilot.flybyodoo.pt/.ssh/id_zebra_win"
WIN_HOST = "asus1@100.127.58.18"


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def action_confirm(self):
        res = super().action_confirm()
        for rec in self:
            rec._print_zebra_label()
        return res

    def _print_zebra_label(self):
        mo_name = self.name
        cmd = [
            "ssh", "-i", SSH_KEY,
            "-o", "IdentitiesOnly=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
            WIN_HOST,
            'powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\\print_zpl.ps1 '
            '-MoName "%s" -QrData "%s"' % (mo_name, mo_name),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if "PRINTED" not in result.stdout:
                _logger.warning(
                    "Falha a imprimir etiqueta MO %s: stdout=%s stderr=%s",
                    mo_name, result.stdout, result.stderr,
                )
        except Exception:
            _logger.exception("Excecao a imprimir etiqueta MO %s", mo_name)

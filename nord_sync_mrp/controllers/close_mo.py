# -*- coding: utf-8 -*-
"""nordCount -> Odoo: closes an MO from a call.

    GET/POST  /nordwire/close-mo/<token>/<code read from the MO's QR code>

The code is the MO's reference (what its QR code holds): that MO is closed
with its planned quantity, as the PDA's "Fechar MO" does. One token for the
whole database (Settings > Manufacturing), generated there; it is the only
credential.
"""
import hmac
import json
import logging

from odoo.exceptions import UserError
from odoo.http import Controller, request, route

from .pda import webhook, wake_core

_logger = logging.getLogger(__name__)


class NordSyncCloseMo(Controller):

    @route('/nordwire/close-mo/<string:token>',
           type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def close_mo_body(self, token, **kwargs):
        """nordCount's call: a JSON body with everything the phone identified —
        {"article": ..., "codes": ["WH/MO/00043", ...], ...}. The first code
        that is the reference of an open MO closes that MO; the whole body is
        logged either way (nordCount Requests)."""
        env = request.env(su=True)
        try:
            body = json.loads(request.httprequest.get_data(as_text=True) or '{}')
            if not isinstance(body, dict):
                body = {}
        except ValueError:
            body = {}
        codes = [str(c).strip() for c in (body.get('codes') or []) if str(c).strip()]
        summary = (f"article={body.get('article')} codes={codes} count={body.get('count')} "
                   f"counted_at={body.get('counted_at')}")
        expected = env['ir.config_parameter'].get_param('nord_sync_mrp.close_mo_token')
        if not expected or not hmac.compare_digest(expected.encode(), token.encode()):
            self._log(env, ', '.join(codes), 'invalid_token', 404, 'Link inválido.')
            return self._answer(404, False, 'Link inválido.')
        if not codes:
            message = f'Sem códigos QR no pedido ({summary})'
            self._log(env, '', 'no_codes', 200, message)
            return self._answer(200, False, message)
        productions = env['mrp.production']
        for code in codes:
            productions |= self._find(env, code)
        production = productions.filtered(lambda m: m.state not in ('done', 'cancel'))[:1] or productions[:1]
        if not production:
            message = f'Nenhum código corresponde a uma MO ({summary})'
            self._log(env, ', '.join(codes), 'not_found', 404, message)
            return self._answer(404, False, message)
        return self._close(env, production, ', '.join(codes))

    @route('/nordwire/close-mo/<string:token>/<path:code>',
           type='http', auth='public', methods=['GET', 'POST'], csrf=False, save_session=False)
    def close_mo(self, token, code, **kwargs):
        env = request.env(su=True)
        code = (code or '').strip()
        expected = env['ir.config_parameter'].get_param('nord_sync_mrp.close_mo_token')
        if not expected or not hmac.compare_digest(expected.encode(), token.encode()):
            # Same answer for any bad token: nothing to learn from it
            self._log(env, code, 'invalid_token', 404, 'Link inválido.')
            return self._answer(404, False, 'Link inválido.')
        production = self._find(env, code)
        if not production:
            message = f'{code}: MO não encontrada.'
            self._log(env, code, 'not_found', 404, message)
            return self._answer(404, False, message)
        return self._close(env, production, code)

    @staticmethod
    def _find(env, code):
        """The MO a label refers to: its name (WH/MO/00043) or, for labels from
        another system (SKC/MOI/01010), its Source Document (origin). Open MOs
        win over finished ones."""
        mos = env['mrp.production'].search(
            ['|', ('name', '=ilike', code), ('origin', '=ilike', code)])
        return mos.filtered(lambda m: m.state not in ('done', 'cancel'))[:1] or mos[:1]

    def _close(self, env, production, code):
        try:
            success, message = production._nord_sync_force_close()
        except UserError as error:
            message = f'{production.name}: {error}'
            self._log(env, code, 'refused', 409, message, production)
            return self._answer(409, False, message, production.name)
        except Exception:  # noqa: BLE001 - the caller gets a clean error, the log the detail
            _logger.exception('nordCount close-mo %s failed', production.name)
            message = f'{production.name}: erro ao fechar.'
            env.cr.rollback()
            self._log(env, code, 'error', 500, message, production)
            return self._answer(500, False, message, production.name)
        if success:
            wake_core(env)
            webhook(env, 'close_mo', {'mo': production.name, 'state': production.state})
        status = 200 if success else 409
        self._log(env, code, 'closed' if success else 'refused', status, message, production)
        return self._answer(status, success, message, production.name)

    @staticmethod
    def _log(env, code, outcome, status, message, production=None):
        """One row per call, in its own try: a failed log never changes the answer."""
        try:
            env['nord_sync.close.request'].create({
                'code': code[:200], 'outcome': outcome, 'http_status': status,
                'message': message[:1000], 'production_id': production.id if production else False,
                'remote_ip': request.httprequest.headers.get('X-Forwarded-For', request.httprequest.remote_addr),
            })
            env.cr.commit()
        except Exception:  # noqa: BLE001
            _logger.exception('nordCount close-mo: could not log the request')

    @staticmethod
    def _answer(status, success, message, mo=False):
        return request.make_response(
            json.dumps({'success': success, 'message': message, 'mo': mo}),
            headers=[('Content-Type', 'application/json')], status=status)

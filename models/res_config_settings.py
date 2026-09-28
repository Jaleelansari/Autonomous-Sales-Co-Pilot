import json
import time
import urllib.error
import urllib.request

from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    nvidia_api_key = fields.Char(
        string='NVIDIA API Key',
        config_parameter='sale_ai_copilot.nvidia_api_key',
        help='API key used to generate draft sales quotations from leads using the NVIDIA z-ai/glm-5.3-flash model.',
    )

    # Legacy compatibility: some older installs may still store the older key under the
    # old parameter name. This field is intentionally not used in the visible XML UI,
    # but it avoids registry mismatches when the settings model is reloaded.
    gemini_api_key = fields.Char(
        string='Legacy API Key',
        config_parameter='sale_ai_copilot.gemini_api_key',
        help='Compatibility field retained for older saved values. The active module uses NVIDIA keys.',
    )

    def _get_api_key_for_test(self):
        key = (
            self.nvidia_api_key
            or self.gemini_api_key
            or self.env['ir.config_parameter'].sudo().get_param('sale_ai_copilot.nvidia_api_key')
            or self.env['ir.config_parameter'].sudo().get_param('sale_ai_copilot.gemini_api_key')
        )
        if not key:
            raise UserError(_('Please set your NVIDIA API key first.'))
        return key

    def action_test_nvidia_api(self):
        api_key = self._get_api_key_for_test()
        payload = {
            'model': 'z-ai/glm-5.3-flash',
            'messages': [
                {'role': 'user', 'content': 'Reply with exactly: OK'}
            ],
            'max_tokens': 8,
            'temperature': 0.0,
        }
        req = urllib.request.Request(
            'https://integrate.api.nvidia.com/v1/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json',
                'User-Agent': 'Odoo-Sale-AI-Copilot/1.0',
            },
            method='POST',
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                body = json.loads(resp.read().decode('utf-8'))
                content = body.get('choices', [{}])[0].get('message', {}).get('content', '')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'ignore')
            raise UserError(_(f'NVIDIA API test failed: HTTP {exc.code} - {detail}')) from exc
        except Exception as exc:
            raise UserError(_(f'NVIDIA API test failed: {exc}')) from exc

        if not content or 'OK' not in content.upper():
            raise UserError(_('NVIDIA API responded, but the test payload did not return the expected response.'))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('NVIDIA API test successful'),
                'message': _('The NVIDIA API key and model are working correctly.'),
                'type': 'success',
                'sticky': False,
            },
        }

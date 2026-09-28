import base64
import io
import json
import os
import re
import time
import urllib.request
import urllib.error

from odoo import _, api, fields, models
from odoo.exceptions import UserError

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    ai_quote_count = fields.Integer(
        string='AI Quotes',
        compute='_compute_ai_quote_count',
        groups='base.group_user',
    )

    @api.depends('order_ids')
    def _compute_ai_quote_count(self):
        for lead in self:
            lead.ai_quote_count = len(lead.order_ids)

    def _get_nvidia_api_key(self):
        key = (
            self.env['ir.config_parameter'].sudo().get_param('sale_ai_copilot.nvidia_api_key')
            or self.env['ir.config_parameter'].sudo().get_param('sale_ai_copilot.gemini_api_key')
            or os.getenv('NVIDIA_API_KEY')
        )
        if not key:
            raise UserError(_('Missing NVIDIA API key. Set it in Settings or via the NVIDIA_API_KEY environment variable.'))
        return key

    def _get_gemini_api_key(self):
        return self._get_nvidia_api_key()

    def _extract_inquiry_text(self):
        text_parts = []
        if self.description:
            text_parts.append(self.description)
        if self.name:
            text_parts.append(self.name)

        attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'crm.lead'),
            ('res_id', '=', self.id),
        ])

        if PdfReader is None:
            return '\n\n'.join(part for part in text_parts if part)

        for attachment in attachments:
            filename = attachment.name or ''
            if not filename.lower().endswith('.pdf') and attachment.mimetype != 'application/pdf':
                continue
            data = attachment.raw or (base64.b64decode(attachment.datas, validate=True) if attachment.datas else None)
            if not data:
                continue
            try:
                reader = PdfReader(io.BytesIO(data))
                for page in reader.pages:
                    page_text = page.extract_text() or ''
                    if page_text.strip():
                        text_parts.append(page_text.strip())
            except Exception:
                continue

        return '\n\n'.join(part for part in text_parts if part)

    def _call_nvidia_ai(self, inquiry_text):
        api_key = self._get_nvidia_api_key()
        url = 'https://integrate.api.nvidia.com/v1/chat/completions'

        prompt = (
            "Analyze this inbound customer RFQ and extract all product quotation line items.\n"
            "Return strictly a raw JSON object with this exact structure and no conversational text or markdown:\n"
            "{\n"
            '  "customer_name": "string",\n'
            '  "customer_email": "string",\n'
            '  "items": [\n'
            '    {\n'
            '      "product_hint": "exact product name or SKU",\n'
            '      "quantity": 10\n'
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Inbound RFQ Text:\n"
            f"{inquiry_text}"
        )

        payload = {
            "model": "z-ai/glm-5.3-flash",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a professional enterprise quotation engine. You parse text and output valid raw JSON only according to the user instructions."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"}
        }

        last_error = None
        for attempt in range(1, 4):
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json',
                    'User-Agent': 'Odoo-Sale-AI-Copilot/1.0'
                },
                method='POST'
            )
            try:
                with urllib.request.urlopen(req, timeout=45) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    raw_content = result['choices'][0]['message']['content']
                return self._parse_json_response(raw_content)
            except urllib.error.HTTPError as e:
                last_error = e
                body = e.read().decode('utf-8', 'ignore')
                if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                    time.sleep(attempt * 2)
                    continue
                raise UserError(_(f'NVIDIA API Error ({e.code}): {body}')) from e
            except Exception as e:
                last_error = e
                if attempt < 3 and isinstance(e, (TimeoutError, OSError)):
                    time.sleep(attempt * 2)
                    continue
                raise UserError(_(f'Failed to communicate with NVIDIA API: {str(e)}')) from e

        if last_error:
            raise UserError(_(f'NVIDIA API request failed after retries: {last_error}'))
        raise UserError(_('NVIDIA API request failed after retries.'))

    def _parse_json_response(self, raw_text):
        if not raw_text:
            raise UserError(_('NVIDIA AI returned an empty response.'))

        cleaned = raw_text.strip()
        if cleaned.startswith('```'):
            cleaned = cleaned.strip('`')
            if cleaned.lower().startswith('json'):
                cleaned = cleaned[4:].strip()
        try:
            parsed = json.loads(cleaned)
        except ValueError:
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start == -1 or end == -1 or end < start:
                raise UserError(_('NVIDIA AI response was not valid JSON.'))
            parsed = json.loads(cleaned[start:end + 1])

        if not isinstance(parsed, dict):
            raise UserError(_('NVIDIA AI response did not match the expected JSON object.'))
        return parsed

    def _resolve_product(self, product_hint):
        hint = (product_hint or '').strip()
        if not hint:
            return False

        normalized = re.sub(r'\s+', ' ', hint).strip()
        domain = [
            '|', '|',
            ('default_code', 'ilike', normalized),
            ('barcode', '=', normalized),
            ('name', 'ilike', normalized),
        ]
        product = self.env['product.product'].search(domain, limit=1)
        if product:
            return product

        # Secondary search using individual key terms (skipping tiny words)
        for token in normalized.split():
            if len(token) < 3:
                continue
            product = self.env['product.product'].search([
                '|', '|',
                ('default_code', 'ilike', token),
                ('barcode', '=', token),
                ('name', 'ilike', token),
            ], limit=1)
            if product:
                return product
        return False

    def _get_inventory_snapshot(self, product, requested_qty):
        qty_available = float(getattr(product, 'qty_available', 0.0) or 0.0)
        virtual_available = float(getattr(product, 'virtual_available', 0.0) or 0.0)
        incoming_qty = float(getattr(product, 'incoming_qty', 0.0) or 0.0)
        outgoing_qty = float(getattr(product, 'outgoing_qty', 0.0) or 0.0)
        reorder_point = float(getattr(product, 'reorder_point', 0.0) or 0.0)

        if virtual_available >= requested_qty:
            stock_status = 'In stock'
            reorder_recommendation = 'No reorder required.'
        elif virtual_available > 0:
            stock_status = 'Low stock'
            shortage = max(requested_qty - virtual_available, 1)
            reorder_recommendation = f'Reorder recommended: {shortage:.0f} units to cover the requested quantity.'
        else:
            stock_status = 'Out of stock'
            shortage = max(requested_qty, 1)
            reorder_recommendation = f'Reorder recommended: {shortage:.0f} units immediately.'

        if reorder_point and virtual_available <= reorder_point:
            reorder_recommendation = (
                f'Reorder recommended: {max(int(max(requested_qty, reorder_point) - virtual_available + 1), 1):.0f} units to restore reorder point.'
            )

        return {
            'qty_available': qty_available,
            'virtual_available': virtual_available,
            'incoming_qty': incoming_qty,
            'outgoing_qty': outgoing_qty,
            'reorder_point': reorder_point,
            'stock_status': stock_status,
            'reorder_recommendation': reorder_recommendation,
        }

    def _build_summary_html(self, order, matched_items, stock_alerts):
        rows = []
        for item in matched_items:
            stock_class = 'text-warning' if item.get('stock_status') == 'Low stock' else 'text-danger' if item.get('stock_status') == 'Out of stock' else 'text-success'
            product = item['product']
            inventory = item.get('inventory') or {}
            rows.append(
                f"<tr><td style='padding:6px;border-bottom:1px solid #ddd;'>{product.display_name}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #ddd;'>{item['quantity']}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #ddd;'>${item['price']:.2f}</td>"
                f"<td style='padding:6px;border-bottom:1px solid #ddd;' class='{stock_class}'><strong>{item['stock_status']}</strong></td></tr>"
            )
        if not rows:
            rows.append('<tr><td colspan="4" style="padding:6px;">No items resolved</td></tr>')

        inventory_lines = []
        for item in matched_items:
            inventory = item.get('inventory') or {}
            product = item['product']
            inventory_lines.append(
                f"<li><strong>{product.display_name}</strong> — On hand: {inventory.get('qty_available', 0.0)}, Available: {inventory.get('virtual_available', 0.0)}, Incoming: {inventory.get('incoming_qty', 0.0)}, Outgoing: {inventory.get('outgoing_qty', 0.0)}. {inventory.get('reorder_recommendation', 'No reorder required.')}</li>"
            )

        inventory_html = ''.join(inventory_lines) or '<li>No inventory data available.</li>'
        stock_alert_html = ''.join(
            f"<li>{alert}</li>" for alert in stock_alerts
        ) or '<li>All items currently in stock.</li>'

        return f'''
            <div style="font-family:Arial,sans-serif;max-width:700px;background:#fdfdfd;padding:12px;border:1px solid #e2e8f0;border-radius:6px;">
                <h3 style="margin-top:0;color:#714B67;">Autonomous AI Quote Summary (NVIDIA NIM - GLM 5.3)</h3>
                <p><strong>Customer:</strong> {order.partner_id.display_name or 'N/A'}</p>
                <p><strong>Generated Quotation:</strong> <a href="/web#id={order.id}&model=sale.order&view_type=form"><strong>{order.name}</strong></a></p>
                <table class="table table-sm" style="width:100%;border-collapse:collapse;margin-top:8px;">
                    <thead>
                        <tr style="background:#f1f5f9;text-align:left;">
                            <th style="padding:6px;border-bottom:2px solid #cbd5e1;">Product</th>
                            <th style="padding:6px;border-bottom:2px solid #cbd5e1;">Qty</th>
                            <th style="padding:6px;border-bottom:2px solid #cbd5e1;">Unit Price</th>
                            <th style="padding:6px;border-bottom:2px solid #cbd5e1;">Stock Check</th>
                        </tr>
                    </thead>
                    <tbody>{''.join(rows)}</tbody>
                </table>
                <div style="margin-top:10px;font-size:13px;">
                    <strong>Inventory Watch:</strong>
                    <ul style="margin:4px 0 0 0;padding-left:18px;">{inventory_html}</ul>
                </div>
                <div style="margin-top:10px;font-size:13px;">
                    <strong>Inventory & Fulfillment Checks:</strong>
                    <ul style="margin:4px 0 0 0;padding-left:18px;">{stock_alert_html}</ul>
                </div>
            </div>
        '''

    def action_generate_ai_quotation(self):
        self.ensure_one()

        if PdfReader is None:
            raise UserError(_('The pypdf package is not installed in the Odoo environment.'))

        inquiry_text = self._extract_inquiry_text()
        if not inquiry_text.strip():
            raise UserError(_('No inquiry text or PDF content was found to generate a quotation.'))

        payload = self._call_nvidia_ai(inquiry_text)
        customer_name = (payload.get('customer_name') or '').strip() or self.partner_id.name or self.contact_name or self.name or 'Customer'
        customer_email = (payload.get('customer_email') or '').strip() or (self.partner_id.email or self.email_from or '')
        items = payload.get('items') or []
        if not items:
            raise UserError(_('NVIDIA AI did not detect any line items to quote.'))

        partner = self.partner_id
        if customer_email and not partner:
            partner = self.env['res.partner'].search([('email', '=ilike', customer_email)], limit=1)
        if not partner:
            partner = self.env['res.partner'].create({'name': customer_name, 'email': customer_email or False})

        order = self.env['sale.order'].create({
            'partner_id': partner.id,
            'opportunity_id': self.id,
            'origin': self.name,
            'company_id': self.company_id.id or self.env.company.id,
            'user_id': self.user_id.id or self.env.user.id,
            'team_id': self.team_id.id or False,
        })

        matched_items = []
        stock_alerts = []

        for item in items:
            product_hint = str(item.get('product_hint') or '').strip()
            quantity = float(item.get('quantity') or 0)
            if not product_hint or quantity <= 0:
                continue

            product = self._resolve_product(product_hint)
            if not product:
                raise UserError(_(f'Could not find a matching product in your catalog for: "{product_hint}". Please create the product under Sales > Products first.'))

            inventory = self._get_inventory_snapshot(product, quantity)
            stock_status = inventory['stock_status']
            if stock_status != 'In stock':
                stock_alerts.append(f'{product.display_name}: {stock_status} — {inventory["reorder_recommendation"]} (On hand: {inventory["qty_available"]}, Available: {inventory["virtual_available"]}, Requested: {quantity}).')

            order_line = self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': product.id,
                'product_uom_qty': quantity,
                'price_unit': product.lst_price or product.standard_price or 0.0,
            })
            matched_items.append({
                'product': product,
                'quantity': quantity,
                'price': order_line.price_unit,
                'stock_status': stock_status,
                'inventory': inventory,
            })

        if not matched_items:
            order.unlink()
            raise UserError(_('No valid quotation items were resolved from the AI response.'))

        summary_html = self._build_summary_html(order, matched_items, stock_alerts)
        self.message_post(body=summary_html, subtype_xmlid='mail.mt_comment')
        order.message_post(body=summary_html, subtype_xmlid='mail.mt_comment')

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'view_mode': 'form',
            'res_id': order.id,
            'target': 'current',
        }
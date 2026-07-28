from odoo import models, fields, tools, _, api
from odoo.exceptions import UserError
from datetime import datetime
from markupsafe import Markup
import logging
_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = "account.move"

    it_exemption_status = fields.Boolean(readonly=True)
    it_exemption_cert_no = fields.Char(readonly=True)
    it_exemption_effective_date = fields.Datetime(readonly=True)
    it_exemption_expiry_date = fields.Datetime(readonly=True)
    it_exemption_issue_date = fields.Datetime(readonly=True)

    kra_invoice_number = fields.Char(string="KRA Invoice Number")
    control_unit_invoice_number = fields.Char(string="Control Unit Invoice No.")
    device_serial_number = fields.Char()
    invoice_status = fields.Char()
    transaction_type = fields.Char()
    sales_date = fields.Date()
    transmission_date = fields.Datetime()
    relevant_invoice_number = fields.Char()
    relevant_invoice_date = fields.Date()
    trader_system_invoice_number = fields.Char()
    exemption_certificate_no = fields.Char()
    invoice_checked = fields.Boolean()
    invoice_checked_on = fields.Datetime()
    requires_etims_check = fields.Boolean(compute="_compute_requires_etims_check")

    @api.depends("partner_id")
    def _compute_requires_etims_check(self):
        for move in self:
            partner = move.partner_id
            move.requires_etims_check = bool(
                partner
                and partner.country_id
                and partner.country_id.code == "KE"
                and partner.tax_obligation_ids
            )

    def action_post(self):
        for move in self.filtered(lambda m: m.move_type == "in_invoice"):
            move._check_supplier_it_exemption()
        return super().action_post()

    def _check_supplier_it_exemption(self):
        self.ensure_one()
        partner = self.partner_id
        if not partner.vat or not partner.it_exemption_cert_no:
            return

        try:
            partner.action_check_it_exemption()
        except Exception:
            # Don't let a KRA/eTIMS outage block the user from posting a bill.
            _logger.exception(
                "IT exemption check failed for partner %s on move %s",
                partner.id,
                self.id,
            )
            return

        self.write(
            {
                "it_exemption_status": partner.it_exemption_status,
                "it_exemption_certificate_no": partner.it_exemption_cert_no,
                "it_exemption_effective_date": partner.it_exemption_effective_date,
                "it_exemption_expiry_date": partner.it_exemption_expiry_date,
                "it_exemption_issue_date": partner.it_exemption_issue_date,
            }
        )

    def action_invoice_checker(self):
        self.ensure_one()

        if not self.kra_invoice_number:
            raise UserError(_("Please enter the KRA Invoice Number."))

        invoice = self._check_invoice()
        partner = self._get_or_create_supplier(invoice)
        vals = self._prepare_invoice_vals(invoice, partner)
        self.write(vals)

        self._create_invoice_lines(invoice.get("itemDetails", []))
        self.message_post(
            body=Markup(
                _("Invoice <b>%s</b> imported successfully from KRA.")
                % self.kra_invoice_number
            )
        )

    def _check_invoice(self):
        invoice_date = (
            self.invoice_date.strftime("%Y-%m-%d") if self.invoice_date else False
        )

        response = self.env["gava.api"].check_invoice(
            invoice_number=self.kra_invoice_number,
            invoice_date=invoice_date,
        )
        if response.get("status") != "OK":
            error_desc = response.get("responseDesc") or _(
                "The KRA invoice check failed for an unknown reason."
            )
            self.message_post(
                body=Markup(error_desc),
                message_type="notification",
                subtype_xmlid="mail.mt_note",
            )
            raise UserError(error_desc)

        return response["invoiceDetails"]

    def _get_or_create_supplier(self, invoice):
        pin = invoice.get("supplierPIN")
        partner = self.env["res.partner"].search([("vat", "=", pin)], limit=1)
        if partner:
            return partner

        return self.env["res.partner"].create(
            {
                "name": invoice.get("supplierName"),
                "vat": pin,
                "supplier_rank": 1,
                "company_type": "company",
            }
        )

    @staticmethod
    def _to_date(value):
        """Convert API date string ('YYYY-MM-DD') to a python date."""
        if not value:
            return False
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            _logger.warning("Unexpected date format from KRA API: %s", value)
            return False

    @staticmethod
    def _to_datetime(value):
        """Convert API datetime string to a python datetime.

        Accepts both 'YYYY-MM-DDTHH:MM:SS' and a plain 'YYYY-MM-DD' just in
        case the API sends a date-only value for one of the datetime fields.
        """
        if not value:
            return False
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        _logger.warning("Unexpected datetime format from KRA API: %s", value)
        return False

    def _prepare_invoice_vals(self, invoice, partner):
        return {
            "partner_id": partner.id,
            "invoice_date": self._to_date(invoice.get("invoiceDate")),
            "sales_date": self._to_date(invoice.get("salesDate")),
            "transmission_date": self._to_datetime(invoice.get("transmissionDate")),
            "device_serial_number": invoice.get("deviceSerialNumber"),
            "control_unit_invoice_number": invoice.get("controlUnitInvoiceNumber"),
            "trader_system_invoice_number": invoice.get("traderSystemInvoiceNumber"),
            "invoice_status": invoice.get("invoiceStatus"),
            "transaction_type": invoice.get("transactionType"),
            "relevant_invoice_number": invoice.get("relevantInvoiceNumber"),
            "relevant_invoice_date": self._to_date(invoice.get("relevantInvoiceDate")),
            "exemption_certificate_no": invoice.get("exemptionCertificateNo"),
            "invoice_checked": True,
            "invoice_checked_on": fields.Datetime.now(),
        }

    def _get_or_create_products(self, items):
        """Return {item_code: product} for every item, in at most 2 queries."""
        Product = self.env["product.product"]
        codes = list({item.get("itemCode") for item in items if item.get("itemCode")})

        existing = Product.search([("default_code", "in", codes)]) if codes else Product
        by_code = {p.default_code: p for p in existing}

        for item in items:
            code = item.get("itemCode")
            if code and code not in by_code:
                by_code[code] = Product.create(
                    {
                        "name": item.get("itemName"),
                        "default_code": code,
                        "purchase_ok": True,
                    }
                )
        return by_code

    def _get_purchase_taxes(self, items):
        """Return {rate: tax} for every distinct tax rate used, in 1 query."""
        Tax = self.env["account.tax"]
        rates = {
            item.get("taxRate") for item in items if item.get("taxRate") is not None
        }
        if not rates:
            return {}

        taxes = Tax.search(
            [
                ("amount", "in", list(rates)),
                ("type_tax_use", "=", "purchase"),
                ("company_id", "=", self.company_id.id),
            ]
        )
        by_rate = {}
        for rate in rates:
            match = next(
                (
                    t
                    for t in taxes
                    if tools.float_compare(t.amount, rate, precision_digits=2) == 0
                ),
                None,
            )
            if not match:
                raise UserError(
                    _(
                        "Purchase tax %.2f%% was not found.\n\n"
                        "Please configure this tax before importing the invoice."
                    )
                    % rate
                )
            by_rate[rate] = match
        return by_rate

    def _prepare_invoice_line_vals(self, item, product, tax):
        return {
            "product_id": product.id,
            "name": item.get("itemName"),
            "quantity": item.get("quantity"),
            "price_unit": item.get("unitPrice"),
            "discount": item.get("discountRate") or 0,
            "tax_ids": [(6, 0, tax.ids)],
            "sequence": item.get("itemSequence"),
            "item_code": item.get("itemCode"),
            "item_class_code": item.get("itemClassCode"),
            "tax_type_code": item.get("taxTypeCode"),
            "packaging_unit_code": item.get("packagingUnitCode"),
            "country_of_origin": item.get("countryOfOrigin"),
            "packaging": item.get("packaging"),
            "discount_amount": item.get("discountAmount"),
        }

    def _create_invoice_lines(self, items):
        if not items:
            self.invoice_line_ids.unlink()
            return

        products_by_code = self._get_or_create_products(items)
        taxes_by_rate = self._get_purchase_taxes(items)

        line_commands = [(5, 0, 0)]  # drop existing lines
        for item in items:
            product = products_by_code.get(item.get("itemCode"))
            tax = taxes_by_rate.get(item.get("taxRate"))
            vals = self._prepare_invoice_line_vals(item, product, tax)
            line_commands.append((0, 0, vals))
        self.write({"invoice_line_ids": line_commands})


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    item_code = fields.Char()
    item_class_code = fields.Char()
    tax_type_code = fields.Char()
    country_of_origin = fields.Char()
    packaging = fields.Char()
    packaging_unit_code = fields.Char()
    quantity_unit_code = fields.Char()
    discount_amount = fields.Monetary(
        string="Discount Amount",
        currency_field="currency_id",
        readonly=True,
    )

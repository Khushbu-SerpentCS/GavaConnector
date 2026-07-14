from odoo import fields, models, api, _
from odoo.exceptions import UserError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    it_exemption_status = fields.Boolean(readonly=True)
    it_exemption_cert_no = fields.Char(readonly=True)
    it_exemption_effective_date = fields.Datetime(readonly=True)
    it_exemption_expiry_date = fields.Datetime(readonly=True)
    it_exemption_issue_date = fields.Datetime(readonly=True)
    import_cert_no = fields.Char(string="Import Certificate No")
    tax_certificate_id = fields.Many2one('tax.certificate',
                                         string="Tax Import Certificate",
                                         tracking=True)
    tax_certificate_issue_date = fields.Datetime(string="Tax Import")
    tax_certificate_status = fields.Char(string="Tax Certificate Status")

    def button_confirm(self):
        res = super().button_confirm()

        for order in self:
            order._check_supplier_it_exemption()

        return res

    def action_check_import_cert_by_number(self):
        self.ensure_one()
        if not self.tax_certificate_id:
            raise UserError(_("Please enter an Import Certificate Number."))

        certificate = self.partner_id.certificate_ids.filtered(
                lambda c: c.certificate_no == self.tax_certificate_id.certificate_no
                )[:1]

        if certificate:
            result = certificate.action_check_import_certificate_by_num()
        else:
            temp_certificate = self.env["tax.certificate"].new({
                    "partner_id"    : self.partner_id.id,
                    "certificate_no": self.import_cert_no,
                    })

            result = temp_certificate.action_check_import_certificate_by_num()

            if result["success"]:
                certificate = self.env["tax.certificate"].create({
                        "partner_id"    : self.partner_id.id,
                        "certificate_no": self.import_cert_no,
                        **result["values"],
                        })

        if not result["success"]:
            raise UserError(result["message"])

        self.write({
                "tax_certificate_id"        : certificate.id,
                "tax_certificate_issue_date": certificate.issue_date,
                "tax_certificate_status"    : certificate.status,
                })

    def _check_supplier_it_exemption(self):
        self.ensure_one()

        partner = self.partner_id

        if not partner.kra_pin:
            return

        if not partner.it_exemption_cert_no:
            return

        partner.action_it_exemption_checker()

        self.write({
                "it_exemption_status"        : partner.it_exemption_status,
                "it_exemption_cert_no"       : partner.it_exemption_cert_no,
                "it_exemption_effective_date": partner.it_exemption_effective_date,
                "it_exemption_expiry_date"   : partner.it_exemption_expiry_date,
                "it_exemption_issue_date"    : partner.it_exemption_issue_date,
                })


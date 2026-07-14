from odoo import models, fields

class AccountMove(models.Model):
    _inherit = "account.move"

    it_exemption_status = fields.Boolean(readonly=True)
    it_exemption_cert_no = fields.Char(readonly=True)
    it_exemption_effective_date = fields.Datetime(readonly=True)
    it_exemption_expiry_date = fields.Datetime(readonly=True)
    it_exemption_issue_date = fields.Datetime(readonly=True)

    def action_post(self):

        for move in self.filtered(
                lambda m: m.move_type == "in_invoice"
                ):
            move._check_supplier_it_exemption()

        return super().action_post()

    def _check_supplier_it_exemption(self):
        self.ensure_one()

        partner = self.partner_id

        if not partner.kra_pin:
            return

        if not partner.it_exemption_certificate_no:
            return

        partner.action_check_it_exemption()

        self.write({
                "it_exemption_status"        : partner.it_exemption_status,
                "it_exemption_certificate_no": partner.it_exemption_certificate_no,
                "it_exemption_effective_date": partner.it_exemption_effective_date,
                "it_exemption_expiry_date"   : partner.it_exemption_expiry_date,
                "it_exemption_issue_date"    : partner.it_exemption_issue_date
                })

        # if partner.it_exemption_status == "Approved":
        #     self._apply_zero_wht()
        # else:
        #     self._apply_standard_wht()

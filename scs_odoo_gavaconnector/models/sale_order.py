from odoo import fields, models, api


class SaleOrder(models.Model):
    _inherit = "sale.order"


    def action_confirm(self):
        res = super().action_confirm()
        if self.partner_id:
            print("partner_id>>>>>>>>", self.partner_id)
        return res

from odoo import fields, models, api



class ProductTemplate(models.Model):
    _inherit = "product.template"

    property_type = fields.Selection([
        ("commercial", "Commercial"),
        ("residential", "Residential"),
    ])

    lr_number = fields.Char()
    building = fields.Char()
    street = fields.Char()
    town = fields.Char()

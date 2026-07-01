from odoo import models, fields


class ApiEndpoint(models.Model):
    _name = "api.endpoint"
    _description = "API Endpoint"

    name = fields.Char(required=True, readonly=True)
    code = fields.Char(required=True, readonly=True)
    endpoint = fields.Char(required=True, readonly=True)

{
    "name": "Odoo GavaConnector",
    "version": "19.0.1.0.0",
    "category": "Integrations",
    "summary": "OAuth 2.0 connector for KRA Gava Connect API",
    "description": """
        Odoo GavaConnector
        ===================
        Standardized OAuth 2.0 (Client Credentials) connector for the KRA Gava
        Connect API. Manages access tokens, refresh tokens and provides a single,
        consistent way for any module to call a configured Gava Connect endpoint.
        
        Key Features
        ------------
        - OAuth 2.0 Client Credentials flow with automatic token refresh.
        - A single standardized request layer (``gava.api.call_endpoint``) used by
          every integration point - no more duplicated HTTP-handling code.
        - Self-healing token generation: invalid/expired tokens are detected and
          regenerated automatically, with clear, user-friendly error messages.
        - Scheduled background job to keep tokens warm before they expire.
        - Restricted access: credentials are only visible to the dedicated
          "Gava Connect Administrator" security group.
        - Redesigned UI: status badges, environment statusbar, search/filter/group
          views and a dedicated "Tax Compliance (KRA)" tab on the Contact form.
            """,
    "author": "SerpentCS",
    "depends": ["base", "web", "contacts", "hr", "hr_payroll", "purchase", "sale",
                "account"],
    "data": [
        "security/ir.model.access.csv",
        "data/api_endpoint_data.xml",
        "data/ir_cron_data.xml",
        "views/gava_api_view.xml",
        "views/res_partner_view.xml",
        "views/hr_employee_view.xml",
        "views/purchase_order_view.xml",
        "views/account_move_view.xml",
        "views/menu.xml",
        # 'data/ir_config_parameter.xml',
    ],
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}

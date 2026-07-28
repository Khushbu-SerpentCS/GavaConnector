import logging
from datetime import timedelta, datetime
from odoo.exceptions import ValidationError
import requests
from requests.auth import HTTPBasicAuth
from requests.exceptions import RequestException

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

TOKEN_EXPIRY_BUFFER = 300
DEFAULT_TIMEOUT = 60
DEFAULT_TOKEN_TTL = 3600

BASE_URLS = {
        "sbx"       : "https://sbx.kra.go.ke",
        "production": "https://api.kra.go.ke",
        }


class GavaApi(models.Model):
    _name = "gava.api"
    _description = "Gava Connect API Configuration"
    _order = "state, name"

    _unique_api_endpoint_id = models.Constraint(
        'unique (api_endpoint_id)',
        'An API configuration already exists for this endpoint.',
    )

    name = fields.Char(readonly=True, compute="_compute_name", store=True)
    active = fields.Boolean(default=True)
    description = fields.Char(string="Description")
    api_endpoint_id = fields.Many2one(
            "api.endpoint",
            string="API Endpoint",
            required=True,
            ondelete="restrict",
            )
    state = fields.Selection(
            [("sbx", "Sandbox"), ("production", "Production")], default="sbx",
            required=True
            )
    base_url = fields.Char(
            string="Base URL",
            required=True,
            default=lambda self: BASE_URLS["sbx"],
            )
    client_id = fields.Char(string="Client ID", required=True)
    client_secret = fields.Char(required=True)
    access_token = fields.Char(string="Access Token", readonly=True, copy=False)
    expires_at = fields.Datetime(string="Token Expires At", readonly=True, copy=False)
    token_valid = fields.Boolean(
            string="Token Valid",
            compute="_compute_token_status",
            search="_search_token_valid",
            )
    token_status = fields.Selection(
            [("none", "Not Generated"), ("valid", "Valid"), ("expired", "Expired")],
            string="Token Status",
            compute="_compute_token_status",
            )

    # _sql_constraints = [
    #         (
    #                 "unique_api_endpoint",
    #                 "unique(api_endpoint_id)",
    #                 "An API configuration already exists for this endpoint.",
    #                 )
    #         ]

    # ------------------------------------------------------------
    # Computes / Onchange
    # ------------------------------------------------------------
    @api.depends("api_endpoint_id")
    def _compute_name(self):
        for rec in self:
            rec.name = rec.api_endpoint_id.name or _("New API Configuration")

    @api.depends("access_token", "expires_at")
    def _compute_token_status(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.access_token or not rec.expires_at:
                rec.token_valid = False
                rec.token_status = "none"
            elif rec.expires_at > now:
                rec.token_valid = True
                rec.token_status = "valid"
            else:
                rec.token_valid = False
                rec.token_status = "expired"

    def _search_token_valid(self, operator, value):
        now = fields.Datetime.now()
        is_valid_domain = ["&", ("access_token", "!=", False), ("expires_at", ">", now)]
        want_valid = (operator == "=" and value) or (operator == "!=" and not value)
        if want_valid:
            return is_valid_domain
        return ["|", ("access_token", "=", False), ("expires_at", "<=", now)]

    @api.onchange("state")
    def _onchange_state(self):
        for rec in self:
            if rec.state in BASE_URLS:
                rec.base_url = BASE_URLS[rec.state]

    # ------------------------------------------------------------
    # Token Management
    # ------------------------------------------------------------
    def action_generate_token(self):
        """UI action: manually (re)generate the access token."""
        self.ensure_one()
        self._generate_token()
        return {
                "type"  : "ir.actions.client",
                "tag"   : "display_notification",
                "params": {
                        "title"  : _("Success"),
                        "message": _("Access token generated successfully."),
                        "type"   : "success",
                        "next"   : {"type": "ir.actions.client", "tag": "soft_reload"},
                        },
                }

    def _generate_token(self):
        self.ensure_one()

        if not self.client_id or not self.client_secret:
            raise UserError(
                    _(
                            "Please configure the Client ID and Client Secret before "
                            "generating a token."
                            )
                    )

        response = self._request(
                method="GET",
                endpoint="/v1/token/generate",
                params={"grant_type": "client_credentials"},
                authenticated=False,
                auth=HTTPBasicAuth(self.client_id, self.client_secret),
                )
        token = response.get("access_token")
        if not token:
            raise UserError(
                    _(
                            "Token generation failed: the server did not return an "
                            "access token.\nResponse: %s"
                            )
                    % response
                    )

        expires_in = response.get("expires_in") or DEFAULT_TOKEN_TTL
        try:
            expires_in = int(expires_in)
        except (TypeError, ValueError):
            expires_in = DEFAULT_TOKEN_TTL

        self.write(
                {
                        "access_token": token,
                        "expires_at"  : fields.Datetime.now() + timedelta(
                                seconds=expires_in),
                        }
                )

        _logger.info(
                "Gava API [%s]: access token generated (expires in %s seconds).",
                self.name,
                expires_in,
                )
        return token

    def _needs_new_token(self):
        self.ensure_one()
        if not self.access_token or not self.expires_at:
            return True
        remaining = (self.expires_at - fields.Datetime.now()).total_seconds()
        return remaining < TOKEN_EXPIRY_BUFFER

    def get_valid_token(self):
        """Return a guaranteed-fresh access token, generating one if needed."""
        self.ensure_one()
        if self._needs_new_token():
            self._generate_token()
        return self.access_token

    # ------------------------------------------------------------
    # Standardized API Request Layer
    # ------------------------------------------------------------
    def _request(
            self,
            method,
            endpoint,
            payload=None,
            params=None,
            authenticated=True,
            auth=None,
            retry_on_401=True,
            ):
        """Centralizes header construction, token injection, a single
        automatic retry on a 401 (expired/invalid token).
        """
        self.ensure_one()

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.get_valid_token()}"

        url = f"{(self.base_url or '').rstrip('/')}{endpoint}"
        print("\nmethod->", method, "\nendpoint->", endpoint, "\npayload->", payload,
              "\nauthenticated->", authenticated, "\nauth->", auth)
        try:
            response = requests.request(
                    method=method,
                    url=url,
                    json=payload,
                    params=params,
                    headers=headers,
                    auth=auth,
                    timeout=DEFAULT_TIMEOUT,
                    )
        except RequestException as exc:
            _logger.error("Gava API [%s] request to %s failed: %s", self.name, url, exc)
            raise UserError(
                    _("Unable to reach the Gava Connect API.\n%s") % exc
                    ) from exc

        if response.status_code == 401 and authenticated and retry_on_401:
            _logger.warning(
                    "Gava API [%s]: token rejected (401), regenerating and retrying once.",
                    self.name,
                    )
            self._generate_token()
            return self._request(
                    method,
                    endpoint,
                    payload=payload,
                    params=params,
                    authenticated=authenticated,
                    auth=auth,
                    retry_on_401=False,
                    )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            _logger.error(
                    "Gava API [%s] error %s on %s: %s",
                    self.name,
                    response.status_code,
                    url,
                    response.text,
                    )
            raise UserError(
                    _("Gava Connect API returned an error (%(code)s): %(message)s")
                    % {"code": response.status_code, "message": response.text[:500]}
                    ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise UserError(
                    _("Gava Connect API returned an unexpected (non-JSON) response.")
                    ) from exc

    def call_endpoint(self, payload=None, params=None, method="POST", endpoint=None):
        """Standardized entry point for calling this configuration's API.
        """
        self.ensure_one()
        endpoint = endpoint or self.api_endpoint_id.endpoint
        if not endpoint:
            raise UserError(_('No endpoint path is configured for "%s".') % self.name)

        data = self._request(
                method=method, endpoint=endpoint, payload=payload, params=params
                )
        _logger.info("Gava API [%s]: call to %s completed.", self.name, endpoint)
        return data

    @api.model
    def get_api_by_code(self, code):
        """Return the active API configuration for an endpoint code."""
        return self.search(
                [
                        ("api_endpoint_id.code", "=", code),
                        ("active", "=", True),
                        ],
                limit=1,
                )

    @api.model
    def get_api(self, code):
        """Return the configured API by code."""
        api_config = self.get_api_by_code(code)
        if not api_config:
            raise UserError(_(
                    "This feature is not configured. Please contact your "
                    "administrator to configure the Gava Connect API."
                    ))
        return api_config

    def retrieve_kra_pin(self, taxpayer_type, taxpayer_id):
        api_config = self.get_api("checker_id")
        return api_config.call_endpoint(
                payload={
                        "TaxpayerType": taxpayer_type,
                        "TaxpayerID"  : taxpayer_id,
                        }
                )

    def validate_kra_pin(self, kra_pin):
        """Validate a KRA PIN using the Gava PIN Checker API.

        :param str kra_pin: KRA PIN to validate.
        :return: API response dictionary.
        :rtype: dict
        """
        if not kra_pin:
            raise ValueError(_("KRA PIN is required."))

        api_config = self.get_api("checker_pin")
        return api_config.call_endpoint(
                payload={"KRAPIN": kra_pin}
                )

    def check_invoice(self, invoice_number, invoice_date):
        if not invoice_number:
            raise ValueError(_("Invoice Number is required."))
        api_config = self.get_api("invoice_checker")
        return api_config.call_endpoint(
                payload={"invoiceNumber": invoice_number,
                         "invoiceDate"  : invoice_date }
                )


    def get_kra_tax_station(self, kra_pin):
        api_config = self.get_api_by_code("kra_know_tax_service")
        if not api_config:
            raise UserError(
                    _("The 'Know KRA Tax Service Station' API is not configured.")
                    )

        return api_config.call_endpoint(payload={"kraPIN": kra_pin})

    def check_it_exemption(self, certificate_no):
        api = self.get_api("it_exemption_checker")
        return api.call_endpoint(
                payload={
                        "CertificateNo": certificate_no,
                        }
                )

    def get_tax_obligations(self, kra_pin):
        api = self.get_api("taxpayer_obligations")
        return api.call_endpoint(
                payload={
                        "taxPayerPin": kra_pin,
                        }
                )


class TaxObligation(models.Model):
    _name = "tax.obligation"
    _description = "Tax Obligations"

    name = fields.Char(string="Obligation Name")
    obligationid = fields.Char(string="Obligation ID", required=True)
    obligation_type = fields.Char(string="Obligation Type")
    partner_id = fields.Many2one('res.partner', string="Partner")

    _unique_obligationid = models.Constraint(
        'unique (obligationid)',
        'Obligation ID must be unique.',
    )


class TaxCertificate(models.Model):
    _name = "tax.certificate"
    _description = "Tax Certificate"
    _order = "issue_date desc, id desc"
    _rec_name = "certificate_no"

    partner_id = fields.Many2one(
            "res.partner",
            required=True,
            ondelete="cascade",
            )
    certificate_no = fields.Char(
            required=True,
            index=True,
            )

    status = fields.Char(string="Import Certificate Status")
    issue_date = fields.Date(string="Issued Date")
    product_code = fields.Char(string="Product Code")


    @api.constrains("certificate_no")
    def _check_certificate_no_unique(self):
        for rec in self.filtered("certificate_no"):
            duplicate = self.search([
                    ("certificate_no", "=", rec.certificate_no),
                    ("id", "!=", rec.id),
                    ("partner_id", '=', self.partner_id.id)
            ], limit=1)

            if duplicate:
                raise ValidationError(_(
                    "Import Certificate '%s' already exists"
                ) % (
                    rec.certificate_no,
                ))

    def action_check_import_certificate_by_num(self):
        self.ensure_one()

        if not self.certificate_no:
            raise UserError(
                    _("Please enter an Import Certificate Number first.")
                    )

        api_config = self.partner_id._get_gava_api("import_certificate_num")

        data = api_config.call_endpoint(
                payload={
                        "certificate_no": self.certificate_no
                        }
                )
        error_code = data.get("ErrorCode")
        error_message = data.get("ErrorMessage")
        import_cert_details = data.get("importCertificate_Dtls")
        values = {}

        if data.get("response_code") == "83000":
            issue_date = False
            if import_cert_details:
                cert_details = import_cert_details.get("importCertDtls")[0]

                if cert_details.get("issueDt"):
                    issue_date = datetime.strptime(
                            cert_details["issueDt"],
                            "%Y-%m-%d %H:%M:%S.%f"
                            )
                values = {
                        "status"      : cert_details.get("statusFlag"),
                        "product_code": cert_details.get("productCode"),
                        "issue_date"  : issue_date,
                        }
                if self.id:
                    self.write(values)
            self.partner_id._post_kra_message(_(
                _("Import Certificate %(cert)s verified successfully.") % {
                    "cert": self.certificate_no,
                }
            ))
            return {
                    "success": True,
                    "values" : values,
                    "message": False,
                    }
        elif error_code == "83002":
            message = _(
                    "KRA Import Certificate Checker (By Certificate Number): "
                    "Certificate '%(certificate)s' - %(error)s"
                    ) % {
                              "certificate": self.certificate_no,
                              "error"      : error_message or _("Unknown error"),
                              }

            self.partner_id._post_kra_message(message, success=False)
            return {
                    "success": False,
                    "values" : {},
                    "message": message,
                    }
        else:
            message = _(
                    "KRA Import Certificate Checker (By Certificate Number): "
                    "Certificate '%(certificate)s' - %(error)s"
                    ) % {
                              "certificate": self.certificate_no,
                              "error"      : error_message or _("Unknown error"),
                              }

            self.partner_id._post_kra_message(message, success=False)

            return {
                    "success": False,
                    "values" : {},
                    "message": message,
                    }



class VatExemptionLine(models.Model):
    _name = 'vat.exemption.line'
    _description = 'VAT Exemption Certificate'

    partner_id = fields.Many2one('res.partner', ondelete='cascade')
    cert_no = fields.Char(string="Certificate No")
    issued_date = fields.Datetime(string="Issued Date")
    status_flag = fields.Char(string="Status")


class ExciseLicenceLine(models.Model):
    _name = 'excise.licence.line'
    _description = 'Excise Licence Details'

    is_small_brewer = fields.Boolean(string="Is Small Brewer")
    status = fields.Char(string="Status")
    class_of_goods = fields.Char(string="Class of Goods")
    date_of_issue = fields.Datetime(string="Date of Issue")
    excise_licence_no = fields.Char(string="Excise Licence No")
    partner_id = fields.Many2one('res.partner')

    def action_excise_licence_checker_by_num(self):
        self.ensure_one()

        if not self.excise_licence_no:
            raise UserError(_("Please enter an excise licence number to check."))

        api_config = self.partner_id._get_gava_api("licence_checker_number")

        data = api_config.call_endpoint(
                payload={
                        "ExciseLicenceNo": self.excise_licence_no,
                        }
                )

        if not data:
            raise UserError(_("No response received from the Gava API."))

        response_status = data.get("Status")
        response_code = data.get("ResponseCode")
        error_code = data.get("ErrorCode")
        error_message = data.get("ErrorMessage")

        if error_code == "80002":
            self.partner_id._post_kra_message(
                    _("Excise Licence [%(licence)s]: %(error)s") % {
                            "licence": self.excise_licence_no,
                            "error"  : error_message,
                            },
                    success=False,
                    )
            return

        if response_status == "OK" and response_code == "80000":
            licence = data.get("ExciseLicenseDATA") or {}

            date_of_issue = licence.get("DateOfIssue")
            if date_of_issue:
                date_of_issue = datetime.strptime(
                        date_of_issue, "%d/%m/%Y"
                        ).date()

            # Update licence line
            self.write({
                    "status"           : licence.get("Status"),
                    "class_of_goods"   : licence.get("ClassOfGoods"),
                    "date_of_issue"    : date_of_issue,
                    "excise_licence_no": licence.get("ExciseLicenceNo"),
                    "is_small_brewer"  : licence.get("IsSmallBrewer"),
                    })

            self.partner_id._post_kra_message(
                    _(
                            "Excise Licence %(licence)s validated successfully."
                            ) % {
                            "licence": licence.get("ExciseLicenceNo"),
                            },
                    success=True,
                    )
        else:
            self.partner_id._post_kra_message(
                    _(
                            "KRA Excise Licence Checker by licence number failed: %s"
                            ) % (error_message or _("Unknown error")),
                    success=False,
                    )

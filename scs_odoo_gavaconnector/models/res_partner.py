from datetime import datetime,timedelta

from markupsafe import Markup
import re

from odoo import _, fields, models, api
from odoo.exceptions import UserError, ValidationError

KRA_PIN_REGEX = re.compile(r"^[AP][0-9]{9}[A-Za-z]$")

class ResPartner(models.Model):
    _inherit = "res.partner"

    kra_pin = fields.Char(string="KRA Pin", tracking=True, copy=False)
    kra_validation_status = fields.Selection(
            [
                    ("Active", "Active"),
                    ("Suspended", "Suspended"),
                    ("Cancelled", "Cancelled"),
                    ("Stopped", "Stopped"),
                    ],
            string="Pin Status",
            )
    kra_taxpayer_name = fields.Char(string="Taxpayer Name", copy=False)
    type_of_taxpayer = fields.Char(string="Type of Taxpayer", copy=False)
    kra_last_checked = fields.Datetime(readonly=True, string="PIN Last Checked at",
                                       copy=False)
    tax_payerid = fields.Char(string="Taxpayer ID", copy=False)
    taxpayer_type = fields.Char(string="Taxpayer Type", copy=False)
    taxpayer_dob = fields.Date(string="TaxPayer Date of Birth", copy=False)
    is_pin_with_no_oblig = fields.Boolean(
            string="Is Pin With No Obligations",
            help="If Yes is selected, the PIN will be registered Without tax obligations."
                 "If No is selected, the PIN will be registered With tax obligations.",
            copy=False
            )
    tax_service_station = fields.Char(string="Tax Service Station")
    it_exemption_status = fields.Boolean(
            string="Income Tax Exempt",
            copy=False
            )
    it_exemption_cert_no = fields.Char(
            string="Exemption Certificate No.",
            copy=False
            )
    it_exemption_effective_date = fields.Datetime(
            string="Certificate Effective Date",
            copy=False
            )
    it_exemption_expiry_date = fields.Datetime(
            string="Certificate Expiry Date",
            copy=False
            )
    it_exemption_issue_date = fields.Datetime(
            string="Certificate Issue Date",
            copy=False
            )

    import_certificate_no = fields.Char(
            string="Import Certificate No.",
            copy=False
            )
    import_certificate_status = fields.Char(
            string="Import Certificate Status",
            readonly=True,
            copy=False
            )
    import_certificate_issue_date = fields.Date(
            string="Issue Date",
            readonly=True,
            copy=False
            )
    product_code = fields.Char(
            string="Product Code",
            help="Code or description of the imported product category.",
            copy=False
            )

    tax_obligation_ids = fields.Many2many('tax.obligation')
    certificate_ids = fields.One2many(
            "tax.certificate",
            "partner_id",
            string="Certificates",
            copy=False
            )
    vat_exemption_certificate_no = fields.Char(string="VAT Exemption Certificate No")
    vat_exemption_last_checked = fields.Datetime(readonly=True, copy=False)
    vat_exemption_taxpayer_name = fields.Char(readonly=True, copy=False)
    vat_exemption_line_ids = fields.One2many(
            'vat.exemption.line', 'partner_id',
            string="Exemption Certificates", copy=False

            )
    trading_business_name = fields.Char(string="Trading Business Name", copy=False)
    is_small_brewer = fields.Boolean(string="Is Small Brewer", copy=False)
    excise_licence_status = fields.Char(string="Excise Licence Status", copy=False)
    goods_class = fields.Char(string="Class of Goods", copy=False)
    excise_licence_no = fields.Char(string="Excise Licence No.", copy=False)
    excise_licence_issue_date = fields.Date(string="Excise Licence Issue Date", copy=False)
    excise_licence_last_checked = fields.Datetime(string="Excise Licence "
                                                         "Last Checked", copy=False)
    tcc_reason = fields.Char(string="TCC Reason", help="Short reason for TCC application")
    ack_number = fields.Char(string="Acknowledgment Number",
                             help="Acknowledgment Number issued by iTax confirming the successful Nil return.")
    tcc_number = fields.Char(string="TCC Number", help="Tax Compliance Certificate "
                                                       "Number")
    tcc_status = fields.Char(string="TCC Status", help="Tax Compliance Certificate "
                                                       "status")
    tcc_issue_date = fields.Date(string="TCC Issue Date")
    tcc_expiry_date = fields.Date(string="TCC Expire Date")
    excise_licence_lines = fields.One2many('excise.licence.line', 'partner_id')

    @api.constrains("vat")
    def _check_kra_pin_format(self):
        for partner in self.filtered("vat"):
            pin = partner.vat.strip().upper()

            if not KRA_PIN_REGEX.fullmatch(pin):
                raise ValidationError(_(
                        "Invalid KRA PIN format.\n\n"
                        "Expected format:\n"
                        "• Starts with 'A' or 'P'\n"
                        "• Followed by 9 digits\n"
                        "• Ends with one alphabet\n\n"
                        "Example: A123456789B"
                        ))

    @api.onchange('vat')
    def _onchange_vat(self):
        self.kra_validation_status = ""


    # ------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------
    def _get_gava_api(self, code):
        self.ensure_one()
        api_config = self.env["gava.api"].get_api_by_code(code)
        if not api_config:
            raise UserError(
                    _(
                            "This feature is not configured. Please contact your "
                            "administrator to set up the Gava Connect API."
                            )
                    )
        return api_config

    def _post_kra_message(self, message, success=True):
        self.ensure_one()
        icon = "✅" if success else "❌"
        self.message_post(
                body=Markup("<p>%s %s</p>") % (icon, message),
                subtype_xmlid="mail.mt_note",
                )

    @staticmethod
    def _reload():
        return {"type": "ir.actions.client", "tag": "reload"}

    # ------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------
    def action_validate_kra_pin(self):
        self.ensure_one()
        if not self.vat:
            raise UserError(_("Please enter a KRA PIN."))
        response = self.env['gava.api'].validate_kra_pin(self.vat)

        validation_date = fields.Datetime.now()

        if response.get("ErrorCode") or response.get("Status") != "OK":
            error_message = (
                    response.get("ErrorMessage")
                    or response.get("Message")
                    or _("Unknown error")
            )
            self.write(
                    {
                            "kra_validation_status": False,
                            "kra_taxpayer_name"    : False,
                            "type_of_taxpayer"     : False,
                            # "kra_last_checked": validation_date,
                            }
                    )
            self._post_kra_message(
                    _("KRA PIN validation failed for %(pin)s: %(error)s")
                    % {
                            "pin"  : self.vat,
                            "error": error_message,
                            },
                    success=False,
                    )
            # return self._reload()

        pin_data = response.get("PINDATA", {})
        self.write(
                {
                        "kra_taxpayer_name"    : pin_data.get("Name"),
                        "type_of_taxpayer"     : pin_data.get("TypeOfTaxpayer"),
                        "kra_validation_status": pin_data.get("StatusOfPIN"),
                        # "kra_last_checked": validation_date,
                        }
                )
        self._post_kra_message(
                _("KRA PIN %(pin)s verified successfully - status: %(status)s")
                % {
                        "pin"   : self.vat,
                        "status": self.kra_validation_status,
                        },
                )
        # return self._reload()

    def action_retrieve_kra_pin(self):
        self.ensure_one()
        api_config = self._get_gava_api("checker_id")

        payload = {
                "TaxpayerType": self.taxpayer_type,
                "TaxpayerID"  : self.tax_payerid,
                }
        data = api_config.call_endpoint(payload=payload)

        if data and data.get("ResponseCode") == "30000":
            self.write(
                    {
                            "vat" : data.get("TaxpayerPIN"),
                            "name": data.get("TaxpayerName"),
                            }
                    )
            self._post_kra_message(_("KRA PIN retrieved: %s") % data.get("TaxpayerPIN"))
        else:
            error_message = (
                    data.get("ResponseDescription")
                    or data.get("Message")
                    or _("Unknown error")
            )
            self._post_kra_message(
                    _("Unable to retrieve KRA PIN: %s") % error_message,
                    success=False,
                    )

        # return self._reload()

    def action_know_kra_station(self):
        self.ensure_one()
        if not self.vat:
            raise UserError(_("Please enter a PIN first."))

        api_config = self._get_gava_api("kra_know_tax_service")
        data = api_config.call_endpoint(payload={"kraPIN": self.vat})

        if data and data.get("ResponseCode") == "84000":
            station_data = data.get("STATIONDATA") or {}
            self.tax_service_station = station_data.get("stationName")
            self._post_kra_message(
                    _("Tax service station: %s") % self.tax_service_station
                    )
        else:
            error_message = (
                    data.get("ResponseDescription")
                    or data.get("Message")
                    or _("Unknown error")
            )
            self._post_kra_message(
                    _("Unable to determine tax service station: %s") % error_message,
                    success=False,
                    )

        # return self._reload()

    def action_it_exemption_checker(self):
        self.ensure_one()

        if not self.vat:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("it_exemption_checker")
        data = api_config.call_endpoint(payload={"pin": self.vat})

        response_code = data.get("response_code")
        error_code = data.get("ErrorCode")
        error_message = data.get("ErrorMessage")
        if response_code == "200":
            issue_date = False
            if data.get("cert_issue_date"):
                issue_date = datetime.fromtimestamp(
                        data["cert_issue_date"] / 1000
                        )
            expiry_date = False
            if data.get("cert_expiry_date"):
                expiry_date = datetime.strptime(
                        data["cert_expiry_date"],
                        "%Y-%m-%d %H:%M:%S.%f"
                        )

            effective_date = False
            if data.get("cert_eff_date"):
                effective_date = datetime.strptime(
                        data["cert_eff_date"],
                        "%Y-%m-%d %H:%M:%S.%f"
                        )
            self.write({
                    "it_exemption_status"        : True,
                    "it_exemption_cert_no"       : data.get("cert_no"),
                    "it_exemption_effective_date": effective_date,
                    "it_exemption_expiry_date"   : expiry_date,
                    "it_exemption_issue_date"    : issue_date,
                    })

            self._post_kra_message(
                    _("Valid exemption certificate found: %s")
                    % data.get("cert_no")
                    )

        elif error_code == "900":
            self.write({
                    "it_exemption_status"        : False,
                    "it_exemption_cert_no"       : False,
                    "it_exemption_effective_date": False,
                    "it_exemption_expiry_date"   : False,
                    "it_exemption_issue_date"   : False,
                    })

            self._post_kra_message(
                    _(error_message),
                    success=False,
                    )

        elif error_code == "600":
            self._post_kra_message(
                    _("Invalid KRA PIN."),
                    success=False,
                    )

        else:
            self._post_kra_message(
                    _("Unable to verify exemption certificate."),
                    success=False,
                    )

        # return self._reload()

    def fetch_tax_obligation(self):
        self.ensure_one()

        if not self.vat:
            raise UserError(_("Please enter a PIN first."))

        api_config = self._get_gava_api("taxpayer_obligations")
        data = api_config.call_endpoint(payload={"taxPayerPin": self.vat})
        response_code = data.get("ResponseCode")
        response_msg = data.get("ResponseMsg")
        obligation_list = data.get("ObligationsList") or []
        if response_code == "20000":

            obligation_obj = self.env["tax.obligation"]
            obligation_ids = []

            for obligation in obligation_list:
                obligation_id = obligation.get("obligationId")

                vals = {
                        "name"           : obligation.get("obligationName"),
                        "obligationid"   : obligation_id,
                        "obligation_type": obligation.get("obligationType"),
                        }

                record = obligation_obj.search(
                        [("obligationid", "=", obligation_id)],
                        limit=1,
                        )

                if record:
                    # Keep master data updated
                    record.write({
                            "name"           : vals["name"],
                            "obligation_type": vals["obligation_type"],
                            })
                else:
                    record = obligation_obj.create(vals)

                obligation_ids.append(record.id)

            # Replace partner's obligations with the latest list
            self.tax_obligation_ids = [(6, 0, obligation_ids)]

            self._post_kra_message(
                    _("Tax obligations fetched successfully.")
                    )

        elif response_code == "20001":
            self._post_kra_message(
                    _("KRA Tax Obligations Fetcher failed: %s")
                    % (response_msg or _("Unknown error")),
                    success=False,
                    )

        else:
            self._post_kra_message(
                    _("KRA Tax Obligations Fetcher: Unable to fetch tax obligation details."),
                    success=False,
                    )

        # return self._reload()

    def action_check_import_certificate_by_pin(self):
        self.ensure_one()
        if not self.vat:
            raise UserError(_("Please enter a PIN first."))

        api_config = self._get_gava_api("certificate_checker_by_pin")
        data = api_config.call_endpoint(payload={'pin_no': self.vat})
        response_code = data.get("response_code")
        response_message = data.get("response_message")
        if response_code == "83000":
            certificate_data = (
                    data.get("importCertificate_Dtls", {})
                    .get("importCertDtls", [])
            )
            existing_certificates = {
                    rec.certificate_no: rec
                    for rec in self.certificate_ids
                    }
            received_certificates = set()
            for cert in certificate_data:
                certificate_no = cert.get("certiNo")
                received_certificates.add(certificate_no)
                issue_date = False
                if cert.get("issueDt"):
                    issue_date = datetime.strptime(
                            cert["issueDt"],
                            "%Y-%m-%d %H:%M:%S.%f",
                            ).date()

                vals = {
                        "issue_date"  : issue_date,
                        "status"      : cert.get("statusFlag"),
                        "product_code": cert.get("productCode"),
                        }

                if certificate_no in existing_certificates:
                    existing_certificates[certificate_no].write(vals)
                else:
                    vals.update({
                            "partner_id"    : self.id,
                            "certificate_no": certificate_no,
                            })
                    self.env["tax.certificate"].create(vals)

            # Remove certificates no longer returned by KRA
            obsolete = self.certificate_ids.filtered(
                    lambda r: r.certificate_no not in received_certificates
                    )
            obsolete.unlink()

            self._post_kra_message(
                    _("All Import certificates fetched successfully.")
                    )

        else:
            self._post_kra_message(
                    _("KRA Import Certificate Checker (By PIN) failed: %s")
                    % (response_message or _("Unknown error")),
                    success=False,
                    )

        # return self._reload()

    def action_check_vat_exemption_certificate(self):
        self.ensure_one()
        if not self.vat_exemption_certificate_no:
            raise UserError(_("Please enter a VAT Exemption Certificate Number first."))

        api_config = self._get_gava_api("vat_exemption_checker")
        data = api_config.call_endpoint(
                payload={'VatExemptionCertificateNo': self.vat_exemption_certificate_no}
                )

        response_code = data.get("response_code")
        response_message = data.get("response_message")
        response_status = data.get("response_status")

        if response_status == "OK" and response_code == "83000":
            details = data.get("vatExemptionCertificateDetails", {}) or {}
            lines = details.get("vatExemptionCheckerDtls", []) or []
            self.vat_exemption_line_ids.unlink()
            line_vals = [(0, 0, {
                    'cert_no'    : l.get('certiNo'),
                    'issued_date': l.get('issueDt'),
                    'status_flag': l.get('statusFlag'),
                    }) for l in lines]

            self.write({
                    'vat_exemption_last_checked' : fields.Datetime.now(),
                    'vat_exemption_taxpayer_name': details.get('taxPayerName'),
                    'vat_exemption_line_ids'     : line_vals,
                    })
            self._post_kra_message(
                    _("Vat Exemption Certificate Validated successfully."),
                    success=True,
                    )
        elif response_code == "83002":
            self.write({
                    'vat_exemption_last_checked' : fields.Datetime.now()})
            self._post_kra_message(
                    _(response_message), success=False,
                    )

        else:
            self._post_kra_message(
                    _("KRA VAT Exemption Certificate Checker failed: %s")
                    % (response_message or _("Unknown error")),
                    success=False,
                    )


    def action_excise_licence_checker_by_pin(self):
        self.ensure_one()

        if not self.vat:
            raise UserError(_("Please enter a PIN first."))

        api_config = self._get_gava_api("licence_checker_pin")
        data = api_config.call_endpoint(payload={"PINNo": self.vat})

        response_code = data.get("ResponseCode")
        response_message = data.get("Message")
        response_status = data.get("Status")
        error_message = data.get("ErrorMessage")
        error_code = data.get("ErrorCode")

        if error_code == "80002":
            self._post_kra_message(
                    _(error_message),
                    success=False,
                    )

            self.write({
                    "excise_licence_last_checked": fields.Datetime.now(),
                    })

            self.excise_licence_lines.unlink()

            return

        if response_status == "OK" and response_code == "80000":
            pin_details = data.get("PIN_Details") or {}
            licence_details_list = data.get("ExciseLicenceDetails") or []

            self.write({
                    "excise_licence_last_checked": fields.Datetime.now(),
                    })

            # Replace existing licence records
            self.excise_licence_lines.unlink()

            vals_list = []
            for licence in licence_details_list:
                issue_date = licence.get("DateOfIssue")
                if issue_date:
                    issue_date = datetime.strptime(
                            issue_date, "%d/%m/%Y"
                            ).date()

                vals_list.append({
                        "partner_id"       : self.id,
                        "is_small_brewer"  : licence.get("isSmallBrewer"),
                        "status"           : licence.get("Status"),
                        "class_of_goods"   : licence.get("ClassOfGoods"),
                        "date_of_issue"    : issue_date,
                        "excise_licence_no": licence.get("ExciseLicenceNo"),
                        })

            if vals_list:
                self.env["excise.licence.line"].create(vals_list)

            self._post_kra_message(
                    _("Excise Licence fetched successfully."),
                    success=True,
                    )

        else:
            self._post_kra_message(
                    _("KRA Excise Licence Checker failed: %s")
                    % (response_message or _("Unknown error")),
                    success=False,
                    )

    def action_excise_licence_checker_by_num(self):
        self.ensure_one()
        if not self.excise_licence_no:
            raise UserError(_("Please enter an excise licence number to check."))
        api_config = self._get_gava_api("licence_checker_number")
        data = api_config.call_endpoint(
            payload={'ExciseLicenceNo': self.excise_licence_no})
        response_status = data.get('Status')
        response_code = data.get('ResponseCode')
        error_code = data.get('ErrorCode')
        error_message = data.get('ErrorMessage')
        if not data:
            raise UserError(_("No response received from the Gava API."))
        if error_code == "80002":
            self._post_kra_message(_(error_message), success=False)

        elif response_status == "OK" and response_code == '80000':
            licence = data.get("ExciseLicenseDATA") or {}
            date_of_issue = licence.get("DateOfIssue")

            if date_of_issue:
                date_of_issue = datetime.strptime(
                        date_of_issue, "%d/%m/%Y"
                        ).date()

            self.write({
                    "vat"                        : licence.get("PINNo"),
                    "kra_taxpayer_name"          : licence.get("TaxpayerName"),
                    "name"                       : licence.get("TaxpayerName"),
                    "excise_licence_no"          : licence.get("ExciseLicenceNo"),
                    "excise_licence_status"      : licence.get("Status"),
                    "goods_class"                : licence.get("ClassOfGoods"),
                    "excise_licence_issue_date"  : date_of_issue,
                    'excise_licence_last_checked': fields.Datetime.now()
                    })
            self._post_kra_message(_("Excise Licence Validated successfully."),
                                   success=True)

        else:
            self._post_kra_message(
                    _("KRA Excise Licence Checker by Certificate number failed %s")
                    % (error_message or _("Unknown error")),
                    success=False,
                    )

    def action_pin_registration(self):
        self.ensure_one()
        taxpayer_details_dict = {}
        if not self.taxpayer_type:
            raise UserError(_("Please enter Taxpayer Type."))
        if not self.tax_payerid:
            raise UserError(_("Please enter Taxpayer ID."))
        if not self.taxpayer_dob:
            raise UserError(_("Please enter Taxpayer Date of birth."))
        if not self.phone:
            raise UserError(_("Please enter Taxpayer Phone Number."))
        if not self.email:
            raise UserError(_("Please enter Taxpayer Email."))
        taxpayer_details_dict.update(
                {
                        "TaxpayerType"        : self.taxpayer_type,
                        "IdentificationNumber": self.tax_payerid,
                        "DateOfBirth"         : self.taxpayer_dob.strftime("%d/%m/%Y"),
                        "MobileNumber"        : self.phone,
                        "EmailAddress"        : self.email,
                        "IsPinWithNoOblig"    : "Yes" if self.is_pin_with_no_oblig else "No",
                        }
                )
        api_config = self._get_gava_api("pin_reg_individual")
        data = api_config.call_endpoint(
                payload={"TAXPAYERDETAILS": taxpayer_details_dict})
        response = data.get("RESPONSE", {})
        response_status = response.get("Status")
        response_code = response.get("ResponseCode")
        if response_status == "OK" and response_code == "80000":
            self.vat = response.get("PIN")

            self._post_kra_message(
                    _(
                            "KRA PIN registration completed successfully.\n"
                            "Generated PIN: %s"
                            ) % (self.vat or "-"),
                    success=True,
                    )
        error_message = (
                data.get("ErrorMessage")
                or response.get("Message")
                or _("Unknown error")
        )

        self._post_kra_message(
                _(
                        "KRA PIN registration failed.\n"
                        "Reason: %s"
                        ) % error_message,
                success=False,
                )

    def action_tcc_application(self):
        self.ensure_one()
        if not self.vat:
            raise UserError(_("Please enter Taxpayer PIN Number."))
        if not self.tcc_reason:
            raise UserError(_("Please enter TCC Reason."))
        taxpayer_details_dict = {}
        api_config = self._get_gava_api("tcc_application")
        taxpayer_details_dict.update({
                "TaxpayerPIN": self.vat,
                "ReasonForTCC": self.tcc_reason
                })
        data = api_config.call_endpoint(payload={
                "TAXPAYERDETAILS": taxpayer_details_dict
                })
        response = data.get('RESPONSE') or {}
        if response.get("ResponseCode") == '85000':
            self.ack_number = response.get('AckNumber')
            self.tcc_number = response.get('TCCNumber')
            self._post_kra_message(_("TCC Applied Successfully"), success=True)

        error_message = (
                data.get("ErrorMessage")
                or response.get("Message")
                or _("Unknown error")
        )
        self._post_kra_message(_("Tax Certification Compliance Application Failed.\n"
                                 "Reason: %s")% error_message, success=False)

    def action_tcc_checker(self):
        self.ensure_one()
        if not self.vat:
            raise UserError(_("Please enter Taxpayer PIN Number."))
        if not self.tcc_number:
            raise UserError(_("Please enter TCC Number."))
        api_config = self._get_gava_api("compliance_checker")
        data = api_config.call_endpoint(payload={
                'kraPIN'   : self.vat,
                'tccNumber': self.tcc_number,
                })
        if data.get("ResponseCode") == "83000":
            tcc_data = data.get("TCCData", {})

            self.write({
                    "tcc_status"     : tcc_data.get("TCCStatus"),
                    "tcc_issue_date" : (
                            datetime.strptime(
                                    tcc_data.get("TCCIssueDate"), "%d/%m/%Y"
                                    ).date()
                            if tcc_data.get("TCCIssueDate")
                            else False
                    ),
                    "tcc_expiry_date": (
                            datetime.strptime(
                                    tcc_data.get("TCCExpiryDate"), "%d/%m/%Y"
                                    ).date()
                            if tcc_data.get("TCCExpiryDate")
                            else False
                    ),
                    })

            self._post_kra_message(
                    _(
                            "Tax Compliance Certificate validated successfully.\n\n"
                            "TCC Number: %s\n"
                            "Status: %s"
                            ) % (
                            tcc_data.get("TCCNumber") or "-",
                            tcc_data.get("TCCStatus") or "-",
                            ),
                    success=True,
                    )
            return True

        error_message = (
                data.get("ErrorMessage")
                or data.get("Message")
                or _("Unknown error")
        )

        self._post_kra_message(
                _(
                        "Tax Compliance Certificate validation failed.\n"
                        "Reason: %s"
                        ) % error_message,
                success=False,
                )

        raise UserError(error_message)

    @api.model
    def cron_notify_it_exemption_expiry(self):
        """Notify Accounts Manager and Supplier 30 days before IT exemption expiry."""

        today = fields.Date.today()
        expiry_limit = today + timedelta(days=30)

        partners = self.search([
                ("it_exemption_status", "=", True),
                ("it_exemption_expiry_date", "!=", False),
                ])

        accounts_group = self.env.ref("account.group_account_manager",
                                      raise_if_not_found=False)

        for partner in partners:
            expiry_date = fields.Date.to_date(partner.it_exemption_expiry_date)

            if today <= expiry_date <= expiry_limit:

                # Avoid duplicate notifications
                activity_exists = self.env["mail.activity"].search_count([
                        ("res_model", "=", "res.partner"),
                        ("res_id", "=", partner.id),
                        ("summary", "=", "Income Tax Exemption Certificate Expiring"),
                        ])

                if not activity_exists and accounts_group:
                    for user in accounts_group.users:
                        self.env["mail.activity"].create({
                                "activity_type_id": self.env.ref(
                                        "mail.mail_activity_data_todo"
                                        ).id,
                                "summary"         : _(
                                    "Income Tax Exemption Certificate Expiring"),
                                "note"            : _(
                                        "The Income Tax Exemption Certificate for supplier "
                                        "<b>%s</b> will expire on <b>%s</b>.<br/><br/>"
                                        "Certificate No: <b>%s</b><br/>"
                                        "Please request a renewed certificate."
                                        ) % (
                                                            partner.display_name,
                                                            partner.it_exemption_expiry_date,
                                                            partner.it_exemption_cert_no,
                                                            ),
                                "user_id"         : user.id,
                                "res_model_id"    : self.env["ir.model"]._get_id(
                                    "res.partner"),
                                "res_id"          : partner.id,
                                "date_deadline"   : today,
                                })

                # Optional: Notify supplier
                if partner.email:
                    partner.message_post(
                            body=_(
                                    "Your Income Tax Exemption Certificate "
                                    "<b>%s</b> will expire on <b>%s</b>. "
                                    "Please provide a renewed certificate."
                                    ) % (
                                         partner.it_exemption_cert_no,
                                         partner.it_exemption_expiry_date,
                                         ),
                            partner_ids=[partner.id],
                            )

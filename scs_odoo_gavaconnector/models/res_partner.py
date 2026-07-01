from datetime import datetime

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


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
    excise_licence_last_checked = fields.Datetime(string="Excise Licenece "
                                                         "Last Checked", copy=False)


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
        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN."))

        api_config = self._get_gava_api("checker_pin")
        response = api_config.call_endpoint(payload={"KRAPIN": self.kra_pin})

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
                            "pin"  : self.kra_pin,
                            "error": error_message,
                            },
                    success=False,
                    )
            return self._reload()

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
                        "pin"   : self.kra_pin,
                        "status": self.kra_validation_status,
                        },
                )
        return self._reload()

    def action_register_kra_pin(self):
        self.ensure_one()
        api_config = self._get_gava_api("pin_reg_individual")

        if not self.taxpayer_dob:
            raise UserError(
                    _("Please set the Taxpayer Date of Birth before registering a PIN.")
                    )

        payload = {
                "TAXPAYERDETAILS": {
                        "TaxpayerType"        : self.taxpayer_type,
                        "IdentificationNumber": self.tax_payerid,
                        "DateOfBirth"         : fields.Date.to_string(
                                self.taxpayer_dob),
                        "MobileNumber"        : self.mobile,
                        "EmailAddress"        : self.email,
                        "IsPinWithNoOblig"    : "Yes" if self.is_pin_with_no_oblig else "No",
                        }
                }
        response = api_config.call_endpoint(payload=payload)

        new_pin = response.get("TaxpayerPIN") or response.get("PIN")
        if new_pin:
            self.kra_pin = new_pin
            self._post_kra_message(_("KRA PIN registered successfully: %s") % new_pin)
        else:
            error_message = (
                    response.get("ErrorMessage")
                    or response.get("Message")
                    or _("Unknown error")
            )
            self._post_kra_message(
                    _("KRA PIN registration failed: %s") % error_message,
                    success=False,
                    )

        return self._reload()

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
                            "kra_pin"          : data.get("TaxpayerPIN"),
                            "kra_taxpayer_name": data.get("TaxpayerName"),
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

        return self._reload()

    def action_know_kra_station(self):
        self.ensure_one()
        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("kra_know_tax_service")
        data = api_config.call_endpoint(payload={"kraPIN": self.kra_pin})

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

        return self._reload()

    def action_it_exemption_checker(self):
        self.ensure_one()

        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("it_exemption_checker")
        data = api_config.call_endpoint(payload={"pin": self.kra_pin})

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

        return self._reload()

    def fetch_tax_obligation(self):
        self.ensure_one()

        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("taxpayer_obligations")
        data = api_config.call_endpoint(payload={"taxPayerPin": self.kra_pin})
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

        return self._reload()

    def action_check_import_certificate_by_pin(self):
        self.ensure_one()
        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("certificate_checker_by_pin")
        data = api_config.call_endpoint(payload={'pin_no': self.kra_pin})
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
                    _("Import certificates fetched successfully.")
                    )

        else:
            self._post_kra_message(
                    _("KRA Import Certificate Checker (By PIN) failed: %s")
                    % (response_message or _("Unknown error")),
                    success=False,
                    )

        return self._reload()

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
        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        api_config = self._get_gava_api("licence_checker_pin")
        data = api_config.call_endpoint(payload={'PINNo': self.kra_pin})
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
                    'trading_business_name'    : False,
                    'is_small_brewer'          : False,
                    'excise_licence_status'    : False,
                    'goods_class'              : False,
                    'excise_licence_issue_date': False,
                    'excise_licence_no'        : False,
                    'excise_licence_last_checked': fields.Datetime.now()
                    })
        elif response_status == "OK" and response_code == "80000":
            pin_details = data.get("PIN_Details") or {}
            licence_details_list = data.get("ExciseLicenceDetails") or []

            # Prefer an Approved licence
            licence_details = next(
                    (licence for licence in licence_details_list
                     if licence.get("Status") == "Approved"),
                    licence_details_list[0] if licence_details_list else {},
                    )
            date_of_issue = licence_details.get("DateOfIssue")

            if date_of_issue:
                date_of_issue = datetime.strptime(
                        date_of_issue, "%d/%m/%Y"
                        ).date()
            self.write({
                    'trading_business_name'      : pin_details.get(
                            'Trading_Business_Name'),
                    'kra_taxpayer_name'          : pin_details.get(
                            'TaxpayerName'),
                    'is_small_brewer'            : licence_details.get(
                            'isSmallBrewer'),
                    'excise_licence_status'      : licence_details.get('Status'),
                    'goods_class'                : licence_details.get(
                            'ClassOfGoods'),
                    'excise_licence_issue_date'  : date_of_issue,
                    'excise_licence_no'          : licence_details.get(
                            'ExciseLicenceNo'),
                    'excise_licence_last_checked': fields.Datetime.now()
                    })
            self._post_kra_message(
                    _("Excise Licence Validated successfully."),
                    success=True,
                    )

        else:
            self._post_kra_message(
                    _("KRA Excise Licence Checker failed %s")
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
                    "kra_pin"                    : licence.get("PINNo"),
                    "kra_taxpayer_name"          : licence.get("TaxpayerName"),
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

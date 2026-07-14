import re

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging
_logger = logging.getLogger(__name__)

KRA_PIN_REGEX = re.compile(r"^[AP][0-9]{9}[A-Za-z]$")


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    kra_pin = fields.Char(string="KRA Pin")
    pin_status = fields.Char(string="KRA Validation Status")
    pin_last_checked = fields.Datetime()
    taxpayer_type = fields.Selection(
            [
                    ("KE", "Kenyan Resident"),
                    ("NKE", "Non-Kenyan Resident"),
                    ("NKENR", "Non-Kenyan Non-Resident"),
                    ],
            string="Taxpayer Type",
            )
    kra_tax_station = fields.Char(string="Tax Station")

    @api.constrains("kra_pin")
    def _check_kra_pin_format(self):
        for employee in self.filtered("kra_pin"):
            pin = employee.kra_pin.strip().upper()

            if not KRA_PIN_REGEX.fullmatch(pin):
                raise ValidationError(_(
                        "Invalid KRA PIN format.\n\n"
                        "Expected format:\n"
                        "• Starts with 'A' or 'P'\n"
                        "• Followed by 9 digits\n"
                        "• Ends with one alphabet\n\n"
                        "Example: A123456789B"
                        ))

    @api.onchange('kra_pin')
    def _onchange_kra_pin(self):
        self.pin_status = ""

    @api.onchange("country_id", "is_non_resident")
    def _onchange_taxpayer_type(self):
        kenya = self.env.ref("base.ke", raise_if_not_found=False)

        if self.country_id == kenya:
            self.taxpayer_type = "NKE" if self.is_non_resident else "KE"
        elif self.country_id:
            self.taxpayer_type = "NKENR"
        else:
            self.taxpayer_type = False

    def _post_kra_message(self, message, success=True):
        self.ensure_one()
        icon = "✅" if success else "❌"
        self.message_post(
                body=Markup("<p>%s %s</p>") % (icon, message),
                subtype_xmlid="mail.mt_note",
                )

    @api.model
    def cron_update_kra_tax_stations(self):
        """Update KRA Tax Service Station for employees with a KRA PIN."""
        employees = self.search([("kra_pin", "!=", False)])

        _logger.info(
                "Starting KRA Tax Service Station update for %s employee(s).",
                len(employees),
                )

        for employee in employees:
            try:
                employee.action_know_kra_station()
            except Exception:
                _logger.exception(
                        "Failed to update KRA Tax Service Station for employee '%s' (%s).",
                        employee.name,
                        employee.id,
                        )
                # Continue with remaining employees
                continue

        _logger.info("Completed KRA Tax Service Station update.")

    def action_verify_pin(self):
        self.ensure_one()
        if not self.kra_pin:
            raise UserError(_("Please Enter KRA PIN"))
        response = self.env['gava.api'].validate_kra_pin(self.kra_pin)
        if response.get("ErrorCode") or response.get("Status") != "OK":
            error_message = (
                    response.get("ErrorMessage")
                    or response.get("Message")
                    or _("Unknown error")
            )
            self.pin_status = error_message if error_message == 'Invalid PIN' else ''
            self._post_kra_message(
                    _("KRA PIN validation failed for %(pin)s: %(error)s")
                    % {
                            "pin"  : self.kra_pin,
                            "error": error_message,
                            },
                    success=False,
                    )
        if response.get("ResponseCode") == '23000':
            pin_data = response.get("PINDATA", {})
            self.pin_status = pin_data.get("StatusOfPIN")
            self._post_kra_message(
                    _("KRA PIN %(pin)s verified successfully - status: %(status)s")
                    % {
                            "pin"   : self.kra_pin,
                            "status": self.pin_status,
                            },
                    )
        self.pin_last_checked = fields.Datetime.now()

    def action_retrieve_kra_pin(self):
        self.ensure_one()

        if not self.identification_id:
            raise UserError(_("Please enter the National ID Number."))

        # taxpayer_type = 'KE' if self.is_non_resident else 'NKE'
        response = self.env["gava.api"].retrieve_kra_pin(
                taxpayer_type=self.taxpayer_type,
                taxpayer_id=self.identification_id,
                )

        if response.get("ResponseCode") == "30000":
            self.write({
                    "kra_pin": response.get("TaxpayerPIN"),
                    # "kra_taxpayer_name": response.get("TaxpayerName"),
                    })

            self._post_kra_message(
                    _(
                            "KRA PIN retrieved successfully.\n\n"
                            "Taxpayer PIN: %(pin)s\n"
                            "Taxpayer Name: %(name)s"
                            ) % {
                            "pin" : response.get("TaxpayerPIN") or "-",
                            "name": response.get("TaxpayerName") or "-",
                            },
                    success=True,
                    )

            return {
                    "type"  : "ir.actions.client",
                    "tag"   : "display_notification",
                    "params": {
                            "title"  : _("Confirm Employee Details"),
                            "message": _(
                                    "KRA PIN has been retrieved successfully.\n\n"
                                    "Please verify that the taxpayer name '%s' matches the "
                                    "employee."
                                    ) % (response.get("TaxpayerName") or "-"),
                            "type"   : "warning",
                            "sticky" : True,
                            },
                    }

        error_message = (
                response.get("ResponseDescription")
                or response.get("Message")
                or response.get("ErrorMessage")
                or _("Unknown error")
        )

        self._post_kra_message(
                _("Unable to retrieve KRA PIN: %s") % error_message,
                success=False,
                )

        raise UserError(error_message)

    def action_know_kra_station(self):
        self.ensure_one()

        if not self.kra_pin:
            raise UserError(_("Please enter a KRA PIN first."))

        response = self.env["gava.api"].get_kra_tax_station(self.kra_pin)

        if response.get("ResponseCode") == "84000":
            station_data = response.get("STATIONDATA") or {}

            self.write({
                    "kra_tax_station": station_data.get("stationName"),
                    })

            self._post_kra_message(
                    _(
                            "KRA Tax Service Station retrieved successfully.\n\n"
                            "PIN: %(pin)s\n"
                            "Station: %(station)s"
                            ) % {
                            "pin"    : self.kra_pin,
                            "station": self.kra_tax_station or "-",
                            }
                    )
            return

        error_message = (
                response.get("ResponseDescription")
                or response.get("Message")
                or response.get("ErrorMessage")
                or _("Unknown error")
        )

        self._post_kra_message(
                _(
                        "Unable to retrieve the KRA Tax Service Station for PIN %(pin)s.\n\n"
                        "Reason: %(reason)s"
                        ) % {
                        "pin"   : self.kra_pin,
                        "reason": error_message,
                        },
                success=False,
                )

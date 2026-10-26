# -*- coding: utf-8 -*-
from odoo import fields, models


class BsrIpmExportWizard(models.TransientModel):
    _name = "bsr.ipm.export.wizard"
    _description = "Download Complete Mastercard IPM Workbook"

    file_data = fields.Binary(string="Complete XLSX", required=True, readonly=True)
    file_name = fields.Char(required=True, readonly=True)

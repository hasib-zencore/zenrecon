from odoo import api, fields, models, _
from odoo.exceptions import UserError


class VisaImportBatch(models.Model):
    _name = 'visa.import.batch'
    _description = 'VISA VX Imported File'
    _order = 'imported_at desc, id desc'

    name = fields.Char(string='File Name', required=True, readonly=True)
    report_type = fields.Selection([
        ('705', 'VX-705'), ('706', 'VX-706'), ('707', 'VX-707'),
        ('725', 'VX-725'), ('727', 'VX-727'),
    ], required=True, readonly=True, index=True)
    file = fields.Binary(string='Original File', attachment=True, readonly=True)
    file_size = fields.Integer(string='File Size (bytes)', readonly=True)
    imported_at = fields.Datetime(default=fields.Datetime.now, readonly=True)
    imported_by = fields.Many2one('res.users', default=lambda s: s.env.user, readonly=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, readonly=True)
    records_705_ids = fields.One2many('visa.vx.705', 'batch_id', string='705 Transactions', readonly=True)
    records_706_ids = fields.One2many('visa.vx.706', 'batch_id', string='706 Transactions', readonly=True)
    records_707_ids = fields.One2many('visa.vx.707', 'batch_id', string='707 Transactions', readonly=True)
    records_725_ids = fields.One2many('visa.vx.725', 'batch_id', string='725 Transactions', readonly=True)
    records_727_ids = fields.One2many('visa.vx.727', 'batch_id', string='727 Transactions', readonly=True)
    record_count = fields.Integer(compute='_compute_record_count', string='Total Records')
    remarks = fields.Text()
    status = fields.Selection([('imported', 'Imported')], default='imported', readonly=True)

    @api.depends('report_type')
    def _compute_record_count(self):
        mapping = {
            '705': 'visa.vx.705', '706': 'visa.vx.706',
            '707': 'visa.vx.707', '725': 'visa.vx.725',
            '727': 'visa.vx.727',
        }
        for batch in self:
            batch.record_count = self.env[mapping[batch.report_type]].search_count([('batch_id', '=', batch.id)]) if batch.id and batch.report_type else 0

    def action_view_records(self):
        self.ensure_one()
        model = {
            '705': 'visa.vx.705', '706': 'visa.vx.706',
            '707': 'visa.vx.707', '725': 'visa.vx.725',
            '727': 'visa.vx.727',
        }[self.report_type]
        return {
            'type': 'ir.actions.act_window', 'name': '%s — %s' % (self.name, self.report_type),
            'res_model': model, 'view_mode': 'list,form',
            'domain': [('batch_id', '=', self.id)], 'target': 'current',
            'context': {'default_batch_id': self.id},
        }

    def action_download_file(self):
        self.ensure_one()
        if not self.file:
            raise UserError(_('No original file is available for this import.'))
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content?model=visa.import.batch&id=%d&field=file&filename_field=name&download=true' % self.id,
            'target': 'self',
        }

    def unlink(self):
        # The ondelete=cascade field on transaction models removes only records
        # that belong to the deleted import batch; unrelated imports are preserved.
        return super().unlink()

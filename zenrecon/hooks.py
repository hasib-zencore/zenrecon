from odoo import SUPERUSER_ID, api


def migrate_legacy_ocl(env):
    """Move legacy OIC rows out of VISA storage into dedicated NPSB tables."""
    old_sequence = env.ref("npsb_settlement.seq_npsb_settlement_report", raise_if_not_found=False)
    new_sequence = env.ref(
        "zenrecon.seq_npsb_settlement_report", raise_if_not_found=False
    )
    if old_sequence and new_sequence and old_sequence != new_sequence:
        new_sequence.number_next_actual = max(
            old_sequence.number_next_actual, new_sequence.number_next_actual
        )

    env.cr.execute("SELECT to_regclass('public.visa_import_batch')")
    if not env.cr.fetchone()[0]:
        return
    env.cr.execute("SELECT to_regclass('public.oic_xml_transaction')")
    legacy_transaction_table = bool(env.cr.fetchone()[0])
    env.cr.execute("SELECT id FROM visa_import_batch WHERE report_type = 'oic' ORDER BY id")
    legacy_batch_ids = [row[0] for row in env.cr.fetchall()]
    if legacy_transaction_table:
        env.cr.execute("SELECT COUNT(*) FROM oic_xml_transaction")
        legacy_transaction_count = env.cr.fetchone()[0]
    else:
        legacy_transaction_count = 0
    if not legacy_batch_ids and not legacy_transaction_count:
        return

    LegacyBatch = env["visa.import.batch"].sudo()
    NpsbImport = env["npsb.ocl.import"].sudo()
    NpsbTransaction = env["npsb.ocl.transaction"].sudo()
    excluded = {"id", "create_uid", "create_date", "write_uid", "write_date", "batch_id"}
    transaction_fields = {
        name
        for name, field in NpsbTransaction._fields.items()
        if field.store and name not in excluded and field.type not in {"one2many", "many2many"}
    }

    batch_map = {}
    for legacy_batch in LegacyBatch.browse(legacy_batch_ids).exists():
        new_batch = NpsbImport.create(
            {
                "name": legacy_batch.name,
                "file": legacy_batch.file,
                "file_size": legacy_batch.file_size,
                "imported_at": legacy_batch.imported_at,
                "imported_by": legacy_batch.imported_by.id,
                "company_id": legacy_batch.company_id.id,
                "remarks": legacy_batch.remarks,
                "status": "imported",
            }
        )
        batch_map[legacy_batch.id] = new_batch

    if legacy_transaction_table:
        env.cr.execute("SELECT * FROM oic_xml_transaction ORDER BY id")
        values_list = []
        fallback_batches = {}
        for row in env.cr.dictfetchall():
            new_batch = batch_map.get(row.get("batch_id"))
            if not new_batch:
                fallback_key = (
                    row.get("batch_id"),
                    row.get("source_file_name") or "Legacy OCL Import",
                    row.get("company_id") or env.company.id,
                    row.get("imported_at"),
                )
                new_batch = fallback_batches.get(fallback_key)
                if not new_batch:
                    new_batch = NpsbImport.create(
                        {
                            "name": fallback_key[1],
                            "imported_at": fallback_key[3],
                            "imported_by": SUPERUSER_ID,
                            "company_id": fallback_key[2],
                            "status": "imported",
                            "remarks": "Migrated from legacy OIC transaction storage.",
                        }
                    )
                    fallback_batches[fallback_key] = new_batch
            values = {
                name: row[name]
                for name in transaction_fields
                if name in row and row[name] is not None
            }
            values["batch_id"] = new_batch.id
            values_list.append(values)
        if values_list:
            NpsbTransaction.create(values_list)
        env.cr.execute("DELETE FROM oic_xml_transaction")
    if legacy_batch_ids:
        LegacyBatch.browse(legacy_batch_ids).unlink()

def post_init_hook(env):
    migrate_legacy_ocl(env)
    for company in env["res.company"].sudo().search([]):
        env["zenrecon.source.workspace"].with_company(company)._workspace_for_company(company)


def migrate(cr, version):
    migrate_legacy_ocl(api.Environment(cr, SUPERUSER_ID, {}))

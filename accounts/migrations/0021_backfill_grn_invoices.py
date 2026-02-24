from django.db import migrations


def backfill_grn_invoices(apps, schema_editor):
    """Create a SupplierInvoice for every InventoryPurchase that has no invoice_ref."""
    InventoryPurchase = apps.get_model('accounts', 'InventoryPurchase')
    SupplierInvoice = apps.get_model('accounts', 'SupplierInvoice')

    orphans = InventoryPurchase.objects.filter(invoice_ref__isnull=True)
    for purchase in orphans:
        invoice = SupplierInvoice.objects.create(
            supplier=purchase.supplier,
            invoice_number=f'GRN-{purchase.id}',
            date=purchase.date,
            total_amount=purchase.total_amount,
            status='Pending',
            recorded_by=purchase.recorded_by,
        )
        purchase.invoice_ref = invoice
        purchase.save(update_fields=['invoice_ref'])


def reverse_backfill(apps, schema_editor):
    """Reverse: unlink auto-generated invoices (but don't delete them)."""
    InventoryPurchase = apps.get_model('accounts', 'InventoryPurchase')
    SupplierInvoice = apps.get_model('accounts', 'SupplierInvoice')

    auto_invoices = SupplierInvoice.objects.filter(invoice_number__startswith='GRN-')
    InventoryPurchase.objects.filter(invoice_ref__in=auto_invoices).update(invoice_ref=None)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0020_delete_serviceparameters'),
    ]

    operations = [
        migrations.RunPython(backfill_grn_invoices, reverse_backfill),
    ]

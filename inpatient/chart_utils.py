"""IPD patient chart helpers (consumables management)."""

from django.db.models import Sum

from inventory.consumable_utils import available_stock_for_department, is_pharmaceutical_item


def consumable_stock_department_for_user(user):
    from home.models import Departments

    name = 'Mini Pharmacy' if getattr(user, 'role', None) == 'Nurse' else 'Pharmacy'
    return Departments.objects.filter(name__iexact=name).first()


def consumable_dispensed_qty(visit, inventory_item_id):
    from inventory.models import DispensedItem

    if not visit or not inventory_item_id:
        return 0
    return (
        DispensedItem.objects.filter(visit=visit, item_id=inventory_item_id)
        .aggregate(t=Sum('quantity'))['t']
        or 0
    )


def invoice_item_is_consumable_line(invoice_item):
    from home.models import PrescriptionItem

    visit = invoice_item.invoice.visit if invoice_item.invoice_id else None
    if not visit or not invoice_item.inventory_item_id:
        return False
    for pi in PrescriptionItem.objects.filter(
        prescription__visit=visit,
        medication_id=invoice_item.inventory_item_id,
        dispensed=False,
    ):
        if pi.quantity == invoice_item.quantity:
            return False
    return True


def get_ipd_chart_consumables(admission, user):
    """Unified consumable rows for IPD chart management (InpatientConsumable + invoice lines)."""
    from accounts.models import InvoiceItem
    from inpatient.models import InpatientConsumable

    dept = consumable_stock_department_for_user(user)
    visit = admission.visit
    rows = []
    ipd_item_ids_pending = set()

    for req in InpatientConsumable.objects.filter(admission=admission).select_related(
        'item', 'item__category', 'prescribed_by', 'dispensed_by',
    ):
        if is_pharmaceutical_item(req.item):
            continue
        if req.is_dispensed:
            status = 'dispensed'
            status_label = 'Dispensed'
            status_class = 'bg-emerald-100 text-emerald-700'
        elif req.quantity_dispensed > 0:
            status = 'partial'
            status_label = 'Partially dispensed'
            status_class = 'bg-orange-100 text-orange-700'
        else:
            status = 'pending'
            status_label = 'Pending'
            status_class = 'bg-amber-100 text-amber-700'
            ipd_item_ids_pending.add(req.item_id)

        can_modify = (
            admission.status == 'Admitted'
            and req.quantity_dispensed == 0
            and not req.is_dispensed
        )
        rows.append({
            'source': 'ipd',
            'id': req.pk,
            'name': req.item.name,
            'quantity': req.total_quantity,
            'quantity_dispensed': req.quantity_dispensed,
            'status': status,
            'status_label': status_label,
            'status_class': status_class,
            'can_edit': can_modify,
            'can_delete': can_modify,
            'inventory_item_id': req.item_id,
            'available_stock': available_stock_for_department(req.item, dept),
            'at': req.prescribed_at,
            'by': req.prescribed_by,
            'instructions': req.instructions or '',
        })

    if visit:
        invoice_items = InvoiceItem.objects.filter(
            invoice__visit=visit,
            inventory_item__isnull=False,
        ).select_related('inventory_item', 'inventory_item__category', 'invoice__created_by')

        for inv in invoice_items:
            if not invoice_item_is_consumable_line(inv):
                continue
            if is_pharmaceutical_item(inv.inventory_item):
                continue
            if inv.inventory_item_id in ipd_item_ids_pending:
                continue

            dispensed_qty = consumable_dispensed_qty(visit, inv.inventory_item_id)
            if dispensed_qty > 0 or inv.is_dispensed:
                status = 'dispensed'
                status_label = 'Dispensed'
                status_class = 'bg-emerald-100 text-emerald-700'
                can_modify = False
            else:
                status = 'pending'
                status_label = 'Billed / Pending'
                status_class = 'bg-amber-100 text-amber-700'
                can_modify = admission.status == 'Admitted'

            rows.append({
                'source': 'invoice',
                'id': inv.pk,
                'name': inv.name or inv.inventory_item.name,
                'quantity': inv.quantity,
                'quantity_dispensed': dispensed_qty,
                'status': status,
                'status_label': status_label,
                'status_class': status_class,
                'can_edit': can_modify,
                'can_delete': can_modify,
                'inventory_item_id': inv.inventory_item_id,
                'available_stock': available_stock_for_department(inv.inventory_item, dept),
                'at': inv.created_at,
                'by': inv.invoice.created_by if inv.invoice_id else None,
                'instructions': '',
            })

    rows.sort(key=lambda r: r['at'], reverse=True)
    return rows, dept

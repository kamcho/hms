"""Helpers for consumable-only dispensing (exclude drugs / pharmaceuticals)."""


def is_pharmaceutical_item(item):
    """True if item is a drug (linked Medication or Pharmaceuticals category)."""
    from .models import Medication

    if Medication.objects.filter(item_id=item.pk).exists():
        return True
    category = getattr(item, 'category', None)
    if category and 'pharmaceutical' in (category.name or '').lower():
        return True
    return False


def exclude_pharmaceutical_items(queryset):
    """Limit queryset to non-pharmaceutical inventory for consumable dispense."""
    return queryset.filter(medication__isnull=True).exclude(
        category__name__icontains='Pharmaceutical',
    )


def available_stock_for_department(item, department):
    """Stock available for consumable billing/dispense (matches dispense_item rules)."""
    from django.db.models import Sum
    from .models import StockRecord

    if department and (department.name or '').lower() == 'pharmacy':
        return (
            StockRecord.objects.filter(item=item).aggregate(total=Sum('quantity'))['total'] or 0
        )
    if department:
        return (
            StockRecord.objects.filter(item=item, current_location=department)
            .aggregate(total=Sum('quantity'))['total']
            or 0
        )
    return StockRecord.objects.filter(item=item).aggregate(total=Sum('quantity'))['total'] or 0

from django.core.management.base import BaseCommand

from reports.moh717_lines import MOH717_LINES
from reports.models import Moh717LineDefinition


class Command(BaseCommand):
    help = 'Seed MOH 717 outpatient service line definitions'

    def handle(self, *args, **options):
        created = 0
        for row in MOH717_LINES:
            _, was_created = Moh717LineDefinition.objects.update_or_create(
                row_key=row['row_key'],
                defaults={
                    'code': row['code'],
                    'description': row['description'],
                    'category': row['category'],
                    'sort_order': row['sort_order'],
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f'MOH 717 lines ready: {Moh717LineDefinition.objects.count()} total ({created} new).'
        ))

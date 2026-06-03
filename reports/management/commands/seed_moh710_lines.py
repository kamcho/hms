from django.core.management.base import BaseCommand

from reports.moh710_lines import MOH710_SECTION_A_LINES
from reports.models import NvipLineDefinition


class Command(BaseCommand):
    help = 'Seed MOH 710 Section A line definitions for NVIP reports'

    def handle(self, *args, **options):
        created = 0
        for row in MOH710_SECTION_A_LINES:
            _, was_created = NvipLineDefinition.objects.update_or_create(
                row_key=row['row_key'],
                defaults={
                    'antigen': row['antigen'],
                    'age_group': row.get('age_group', ''),
                    'sort_order': row['sort_order'],
                    'section': 'A',
                    'is_active': True,
                },
            )
            if was_created:
                created += 1
        self.stdout.write(self.style.SUCCESS(
            f'MOH 710 lines ready: {NvipLineDefinition.objects.count()} total ({created} new).'
        ))

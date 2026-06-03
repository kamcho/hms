from django.core.management.base import BaseCommand

from reports.moh705b_columns import MOH705B_COLUMNS
from reports.moh705b_lines import MOH705B_LINES
from reports.models import Moh705bColumnDefinition, Moh705bLineDefinition


class Command(BaseCommand):
    help = 'Seed MOH 705B column and disease line definitions'

    def handle(self, *args, **options):
        col_new = 0
        for col in MOH705B_COLUMNS:
            _, created = Moh705bColumnDefinition.objects.update_or_create(
                col_key=col['col_key'],
                defaults={
                    'col_number': col['col_number'],
                    'label': col['label'],
                    'full_label': col['full_label'],
                    'is_active': True,
                },
            )
            if created:
                col_new += 1

        line_new = 0
        for row in MOH705B_LINES:
            _, created = Moh705bLineDefinition.objects.update_or_create(
                row_key=row['row_key'],
                defaults={
                    'line_number': row['line_number'],
                    'disease_name': row['disease_name'],
                    'category': row['category'],
                    'sort_order': row['line_number'] * 10,
                    'is_active': True,
                },
            )
            if created:
                line_new += 1

        self.stdout.write(self.style.SUCCESS(
            f'MOH 705B: {Moh705bColumnDefinition.objects.count()} columns ({col_new} new), '
            f'{Moh705bLineDefinition.objects.count()} lines ({line_new} new).'
        ))

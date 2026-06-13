from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from hr.attendance_service import process_attendance_for_date


class Command(BaseCommand):
    help = 'Build daily attendance records from punches, leave, and off days.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD (default: today)')
        parser.add_argument('--force', action='store_true', help='Overwrite manual entries')

    def handle(self, *args, **options):
        day = timezone.localdate()
        if options.get('date'):
            day = datetime.strptime(options['date'], '%Y-%m-%d').date()
        force = options.get('force', False)
        records = process_attendance_for_date(day, force=force)
        self.stdout.write(self.style.SUCCESS(f'Processed {len(records)} staff for {day}.'))

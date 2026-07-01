from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from hr.zkteco_sync import sync_and_process


class Command(BaseCommand):
    help = 'Pull attendance from ZKTeco K40 devices and refresh rolls for all affected dates.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='YYYY-MM-DD to reprocess after sync (default: today)')

    def handle(self, *args, **options):
        day = timezone.localdate()
        if options.get('date'):
            day = datetime.strptime(options['date'], '%Y-%m-%d').date()

        results = sync_and_process(day)
        if not results:
            self.stdout.write(self.style.WARNING('No active devices configured.'))
        for device, ok, msg, count, _dates in results:
            style = self.style.SUCCESS if ok else self.style.ERROR
            self.stdout.write(style(f'{device.name}: {msg} ({count} new)'))

from django.core.management.base import BaseCommand

from reports.malaria_services import ensure_moh743_commodity_definitions
from reports.models import Moh743CommodityDefinition


class Command(BaseCommand):
    help = 'Seed MOH 743 malaria commodity line definitions'

    def handle(self, *args, **options):
        before = Moh743CommodityDefinition.objects.count()
        ensure_moh743_commodity_definitions()
        total = Moh743CommodityDefinition.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'MOH 743 commodities ready: {total} total ({total - before} new).'
        ))

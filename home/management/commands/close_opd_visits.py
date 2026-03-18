from django.core.management.base import BaseCommand
from django.utils import timezone
from home.models import Visit

class Command(BaseCommand):
    help = 'Automatically closes all active Out-Patient (OPD) visits at the end of the day'

    def handle(self, *args, **options):
        # We target active OUT-PATIENT visits
        active_opd_visits = Visit.objects.filter(
            visit_type='OUT-PATIENT',
            is_active=True
        )
        
        count = active_opd_visits.count()
        
        if count > 0:
            # Bulk update for efficiency
            active_opd_visits.update(is_active=False)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully closed {count} OPD visits at {timezone.now()}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('No active OPD visits to close.')
            )

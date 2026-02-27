from django.core.management.base import BaseCommand
from django.utils import timezone
from home.models import Visit

class Command(BaseCommand):
    help = 'Automatically closes (deactivates) all active Out-Patient (OPD) visits'

    def handle(self, *args, **options):
        # Filter for active OPD visits
        active_opd_visits = Visit.objects.filter(
            visit_type='OUT-PATIENT',
            is_active=True
        )
        
        count = active_opd_visits.count()
        
        if count > 0:
            # Update is_active to False
            active_opd_visits.update(is_active=False)
            self.stdout.write(
                self.style.SUCCESS(f'Successfully closed {count} active OPD visits at {timezone.now()}')
            )
        else:
            self.stdout.write(
                self.style.SUCCESS('No active OPD visits to close.')
            )

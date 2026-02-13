from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from inpatient.models import Admission, ServiceAdmissionLink
from morgue.models import Deceased, PerformedMortuaryService, MorgueAdmission
from accounts.models import Service, Invoice, InvoiceItem
from users.models import User

class Command(BaseCommand):
    help = 'Processes daily bed charges for inpatients and storage fees for the morgue'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('Starting daily charges processing...'))
        
        # System user for automated actions
        system_user = User.objects.filter(is_superuser=True).first()
        today = timezone.now().date()
        
        self.process_inpatient_charges(today, system_user)
        self.process_morgue_charges(today, system_user)
        
        self.stdout.write(self.style.SUCCESS('Daily charges processing completed.'))

    def process_inpatient_charges(self, today, system_user):
        active_admissions = Admission.objects.filter(status='Admitted').select_related('bed', 'bed__ward', 'visit', 'patient')
        from datetime import timedelta
        
        for admission in active_admissions:
            if not admission.bed:
                continue
                
            ward = admission.bed.ward
            # Try to find a matching service in the 'Admission' category
            # We'll try to match ward name or ward type
            service = Service.objects.filter(
                Q(name__icontains=ward.ward_type) & Q(department__name='Inpatient')
            ).first() or Service.objects.filter(
                Q(name__icontains='General Ward') & Q(department__name='Inpatient')
            ).first() or Service.objects.filter(
                Q(name__icontains='Bed') & Q(department__name='Inpatient')
            ).first()

            if not service:
                self.stdout.write(self.style.WARNING(f"No suitable bed charge service found for ward {ward.name} ({ward.ward_type})"))
                continue

            # Catch up logic: Check every day from admitted_at to today
            start_date = admission.admitted_at.date()
            current_date = start_date
            
            while current_date <= today:
                already_charged = ServiceAdmissionLink.objects.filter(
                    admission=admission,
                    service=service,
                    date_provided__date=current_date
                ).exists()

                if not already_charged:
                    with transaction.atomic():
                        ServiceAdmissionLink.objects.create(
                            admission=admission,
                            service=service,
                            quantity=1,
                            date_provided=timezone.make_aware(timezone.datetime.combine(current_date, timezone.datetime.min.time())),
                            provided_by=system_user
                        )
                        
                        invoice = Invoice.objects.filter(visit=admission.visit).exclude(status='Cancelled').first()
                        if not invoice:
                            invoice = Invoice.objects.create(
                                patient=admission.patient,
                                visit=admission.visit,
                                status='Pending',
                                created_by=system_user,
                                notes=f"Auto-generated invoice for Inpatient Admission ADM-{admission.id}"
                            )
                        
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            service=service,
                            name=f"{service.name} - {current_date}",
                            quantity=1,
                            unit_price=service.price
                        )
                        invoice.update_totals()
                    self.stdout.write(self.style.SUCCESS(f"Charged {service.name} for {current_date} to {admission.patient.full_name}"))
                
                current_date += timedelta(days=1)

    def process_morgue_charges(self, today, system_user):
        active_deceased = Deceased.objects.filter(is_released=False)
        storage_service = Service.objects.filter(name__icontains='Storage', department__name='Morgue').first()
        from datetime import timedelta

        if not storage_service:
            self.stdout.write(self.style.WARNING("Daily Storage Fee (Morgue) service not found"))
            return

        for deceased in active_deceased:
            # Check every day from admission to today
            admission_record = deceased.admissions.order_by('admission_datetime').first()
            start_date = admission_record.admission_datetime.date() if admission_record else deceased.created_at.date()
            current_date = start_date
            
            while current_date <= today:
                already_charged = PerformedMortuaryService.objects.filter(
                    deceased=deceased,
                    service=storage_service,
                    date_performed__date=current_date
                ).exists()

                if not already_charged:
                    with transaction.atomic():
                        PerformedMortuaryService.objects.create(
                            deceased=deceased,
                            service=storage_service,
                            quantity=1,
                            date_performed=timezone.make_aware(timezone.datetime.combine(current_date, timezone.datetime.min.time())),
                            performed_by=system_user
                        )
                        
                        invoice = Invoice.objects.filter(deceased=deceased).exclude(status='Cancelled').first()
                        if not invoice:
                            invoice = Invoice.objects.create(
                                deceased=deceased,
                                status='Pending',
                                created_by=system_user,
                                notes=f"Auto-generated invoice for Mortuary Storage - {deceased.tag}"
                            )
                        
                        InvoiceItem.objects.create(
                            invoice=invoice,
                            service=storage_service,
                            name=f"{storage_service.name} - {current_date}",
                            quantity=1,
                            unit_price=storage_service.price
                        )
                        invoice.update_totals()
                    self.stdout.write(self.style.SUCCESS(f"Charged {storage_service.name} for {current_date} to {deceased.full_name}"))
                
                current_date += timedelta(days=1)

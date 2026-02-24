from django.core.management.base import BaseCommand
from home.models import Departments
from accounts.models import Service
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seed departments and services'

    def handle(self, *args, **options):
        departments_data = [
            {'name': 'Reception', 'abbreviation': 'REC'},
            {'name': 'Triage', 'abbreviation': 'TRI'},
            {'name': 'Consultation', 'abbreviation': 'CON'},
            {'name': 'Lab', 'abbreviation': 'LAB'},
            {'name': 'Pharmacy', 'abbreviation': 'PHARM'},
            {'name': 'Imaging', 'abbreviation': 'IMG'},
            {'name': 'Inpatient', 'abbreviation': 'IPD'},
            {'name': 'Morgue', 'abbreviation': 'MOR'},
            {'name': 'Accounts', 'abbreviation': 'ACC'},
            {'name': 'Main Store', 'abbreviation': 'MST'},
            {'name': 'ANC', 'abbreviation': 'ANC-MAT'},
            {'name': 'Procedure Room', 'abbreviation': 'INJ'},
            {'name': 'PNC', 'abbreviation': 'PNC=MAT'},
            {'name': 'CWC', 'abbreviation': 'CWC'},
            {'name': 'Maternity', 'abbreviation': 'MAT'},
            {'name': 'Mini Pharmacy', 'abbreviation': 'MINI'},
            {'name': 'OPD', 'abbreviation': None},
            {'name': 'Consultation Room 2', 'abbreviation': 'CR2'},
            {'name': 'Consultation Room 1', 'abbreviation': 'CR1'},
        ]

        print('Seeding Departments...')
        for dept_data in departments_data:
            Departments.objects.get_or_create(
                name=dept_data['name'],
                defaults={'abbreviation': dept_data['abbreviation']}
            )

        services_data = [

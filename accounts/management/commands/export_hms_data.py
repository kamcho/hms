import os
from django.core.management.base import BaseCommand
from home.models import Departments
from accounts.models import Service
import reprlib

class Command(BaseCommand):
    help = 'Export departments and services to a seed script'

    def handle(self, *args, **options):
        departments = Departments.objects.all()
        services = Service.objects.all()

        output_file = 'accounts/management/commands/seed_hms_data.py'
        
        with open(output_file, 'w') as f:
            f.write("from django.core.management.base import BaseCommand\n")
            f.write("from home.models import Departments\n")
            f.write("from accounts.models import Service\n")
            f.write("from decimal import Decimal\n\n")
            f.write("class Command(BaseCommand):\n")
            f.write("    help = 'Seed departments and services'\n\n")
            f.write("    def handle(self, *args, **options):\n")
            
            # Export Departments
            f.write("        departments_data = [\n")
            for dept in departments:
                f.write(f"            {{'name': {repr(dept.name)}, 'abbreviation': {repr(dept.abbreviation)}}},\n")
            f.write("        ]\n\n")
            
            f.write("        print('Seeding Departments...')\n")
            f.write("        for dept_data in departments_data:\n")
            f.write("            Departments.objects.get_or_create(\n")
            f.write("                name=dept_data['name'],\n")
            f.write("                defaults={'abbreviation': dept_data['abbreviation']}\n")
            f.write("            )\n\n")
            
            # Export Services
            f.write("        services_data = [\n")
                f.write(f"            {{'name': {repr(svc.name)}, 'price': Decimal({repr(str(svc.price))}), 'department_name': {repr(dept_name)}, 'is_active': {svc.is_active}}},\n")
            f.write("        ]\n\n")
            
            f.write("        print('Seeding Services...')\n")
            f.write("        for svc_data in services_data:\n")
            f.write("            dept = None\n")
            f.write("            if svc_data['department_name']:\n")
            f.write("                dept = Departments.objects.filter(name=svc_data['department_name']).first()\n")
            f.write("            \n")
            f.write("            Service.objects.get_or_create(\n")
            f.write("                name=svc_data['name'],\n")
            f.write("                department=dept,\n")
            f.write("                defaults={\n")
            f.write("                    'price': svc_data['price'],\n")
            f.write("                    'is_active': svc_data['is_active']\n")
            f.write("                }\n")
            f.write("            )\n")
            f.write("        print('Seed completed successully!')\n")

        self.stdout.write(self.style.SUCCESS(f'Successfully exported data to {output_file}'))

from django.core.management.base import BaseCommand
from maternity.models import Vaccine

class Command(BaseCommand):
    help = 'Seeds initial clinical vaccines into the catalog'

    def handle(self, *args, **options):
        vaccines = [
            {
                'name': 'Bacillus Calmette-Guérin',
                'abbreviation': 'BCG',
                'description': 'Prevents Tuberculosis',
                'target_diseases': 'Tuberculosis',
                'route': 'Intradermal'
            },
            {
                'name': 'Oral Polio Vaccine',
                'abbreviation': 'OPV',
                'description': 'Prevents Polio',
                'target_diseases': 'Poliomyelitis',
                'route': 'Oral'
            },
            {
                'name': 'Pentavalent Vaccine',
                'abbreviation': 'DPT-HepB-Hib',
                'description': '5-in-1 vaccine',
                'target_diseases': 'Diphtheria, Pertussis, Tetanus, Hepatitis B, Hib',
                'route': 'Intramuscular'
            },
            {
                'name': 'Rotavirus Vaccine',
                'abbreviation': 'ROTA',
                'description': 'Prevents severe diarrhea',
                'target_diseases': 'Rotavirus',
                'route': 'Oral'
            },
            {
                'name': 'Pneumococcal Conjugate Vaccine',
                'abbreviation': 'PCV',
                'description': 'Prevents pneumonia and meningitis',
                'target_diseases': 'Streptococcus pneumoniae',
                'route': 'Intramuscular'
            },
            {
                'name': 'Inactivated Polio Vaccine',
                'abbreviation': 'IPV',
                'description': 'Prevents Polio (Injectable)',
                'target_diseases': 'Poliomyelitis',
                'route': 'Intramuscular'
            },
            {
                'name': 'Measles-Rubella',
                'abbreviation': 'MR',
                'description': 'Prevents Measles and Rubella',
                'target_diseases': 'Measles, Rubella',
                'route': 'Subcutaneous'
            },
            {
                'name': 'Yellow Fever',
                'abbreviation': 'YF',
                'description': 'Prevents Yellow Fever',
                'target_diseases': 'Yellow Fever Virus',
                'route': 'Subcutaneous'
            },
            {
                'name': 'Vitamin A',
                'abbreviation': 'Vit A',
                'description': 'Essential micronutrient supplementation',
                'target_diseases': 'Vitamin A Deficiency',
                'route': 'Oral'
            },
            {
                'name': 'Tetanus Toxoid',
                'abbreviation': 'TT',
                'description': 'Prevents Tetanus',
                'target_diseases': 'Tetanus',
                'route': 'Intramuscular'
            },
            {
                'name': 'Typhoid Conjugate Vaccine',
                'abbreviation': 'TCV',
                'description': 'Prevents Typhoid Fever',
                'target_diseases': 'Typhoid Fever',
                'route': 'Intramuscular'
            },
            {
                'name': 'Human Papillomavirus Vaccine',
                'abbreviation': 'HPV',
                'description': 'Prevents cervical cancer and other HPV-related diseases',
                'target_diseases': 'Human Papillomavirus',
                'route': 'Intramuscular'
            },
        ]

        for v_data in vaccines:
            vaccine, created = Vaccine.objects.get_or_create(
                abbreviation=v_data['abbreviation'],
                defaults=v_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Seeded: {vaccine.name}"))
            else:
                self.stdout.write(self.style.WARNING(f"Exists: {vaccine.name}"))

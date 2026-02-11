from django.core.management.base import BaseCommand
from inventory.models import InventoryCategory


class Command(BaseCommand):
    help = 'Populate inventory with 8 core categories for hospital operations'

    def handle(self, *args, **kwargs):
        categories = [
            (
                'Pharmaceuticals',
                'All medicinal drugs and pharmaceutical preparations including tablets, capsules, syrups, injections, and topical medications'
            ),
            (
                'Injectable Supplies',
                'Syringes, needles, IV cannulas, IV giving sets, butterfly needles, and all injection-related consumables'
            ),
            (
                'Laboratory Supplies',
                'Lab consumables, reagents, test tubes, sample bottles, specimen containers, lab chemicals, slides and coverslips'
            ),
            (
                'Surgical Supplies',
                'Surgical gloves, sutures, scalpels and blades, surgical drapes, gauze, swabs, and surgical instruments'
            ),
            (
                'Wound Care & Dressings',
                'Bandages, gauze pads, adhesive tapes, wound dressings, cotton wool, and wound care materials'
            ),
            (
                'PPE',
                'Personal protective equipment including examination gloves, face masks, surgical gowns, caps, and shoe covers'
            ),
            (
                'Patient Care Supplies',
                'Bed linens, patient gowns, bedpans, urinals, feeding supplies, oxygen masks and tubing'
            ),
            (
                'Diagnostic Consumables',
                'ECG electrodes, thermometer probes and covers, blood pressure cuffs, ultrasound gel, and diagnostic equipment consumables'
            ),
        ]

        created_count = 0
        existing_count = 0

        for name, description in categories:
            category, created = InventoryCategory.objects.get_or_create(
                name=name,
                defaults={'description': description}
            )
            
            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Created category: {name}')
                )
            else:
                existing_count += 1
                self.stdout.write(
                    self.style.WARNING(f'⚠ Category already exists: {name}')
                )

        self.stdout.write(
            self.style.SUCCESS(
                f'\n{"="*60}\n'
                f'Summary:\n'
                f'  - Created: {created_count} new categories\n'
                f'  - Existing: {existing_count} categories\n'
                f'  - Total: {created_count + existing_count} categories\n'
                f'{"="*60}'
            )
        )

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import InventoryItem, InventoryCategory, Medication, DrugClass

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Load drugs from an extracted list into the inventory'

    def handle(self, *args, **kwargs):
        # The extracted data mapped to the required structure
        drug_data = [
            {"desc": "Adrenaline injection", "other": "", "strength": "1mg/ml", "unit": "1 Amp", "price": 150},
            {"desc": "Activated charcoal", "other": "", "strength": "", "unit": "Tab", "price": 20},
            {"desc": "Albendazole suspension", "other": "", "strength": "100mg/5ml", "unit": "dose", "price": 100},
            {"desc": "Albendazole tablets", "other": "", "strength": "400mg", "unit": "Tab", "price": 50},
            {"desc": "Aminophylline injection", "other": "", "strength": "250mg/10ml", "unit": "Amp", "price": 200},
            {"desc": "Aminophylline tablets", "other": "", "strength": "100mg", "unit": "dose", "price": 150},
            {"desc": "Amitriptyline tablets", "other": "", "strength": "25mg", "unit": "dose", "price": 100},
            {"desc": "Amoxycillin Capsules", "other": "Amoxyl", "strength": "250mg", "unit": "Dose", "price": 150},
            {"desc": "Amoxycillin Capsules", "other": "Amoxyl", "strength": "500mg", "unit": "Dose", "price": 300},
            {"desc": "Amoxycillin powder for suspension", "other": "", "strength": "125mg/5ml", "unit": "100ml/bottle", "price": 100},
            {"desc": "Amoxycillin powder for suspension", "other": "", "strength": "250mg/5ml", "unit": "100ml/bottle", "price": 150},
            {"desc": "Amoxycillin/Clavulanic Acid injection", "other": "Augmentin", "strength": "1.2gm", "unit": "Vial", "price": 300},
            {"desc": "Amoxycillin/Clavulanic Acid Suspension", "other": "Augmentin", "strength": "228mg/5ml", "unit": "70ml/bottle", "price": 400},
            {"desc": "Amoxycillin/Clavulanic Acid Suspension", "other": "Augmentin", "strength": "156mg/5ml", "unit": "100ml/bottle", "price": 300},
            {"desc": "Amoxycillin/Clavulanic Acid Tablets", "other": "Augmentin", "strength": "375mg", "unit": "Dose", "price": 600},
            {"desc": "Amoxycillin/Clavulanic Acid Tablets", "other": "Augmentin", "strength": "625mg", "unit": "Dose", "price": 850},
            {"desc": "Ampicillin/Cloxacillin Capsules", "other": "Ampiclox", "strength": "500mg", "unit": "Dose", "price": 350},
            {"desc": "Ampicillin/Cloxacillin Oral Drops", "other": "Neonatal", "strength": "60/30mg per 0.6ml", "unit": "bottle", "price": 150},
            {"desc": "Ampicillin/Cloxacillin suspension", "other": "", "strength": "250mg/5ml", "unit": "Bottle", "price": 100},
            {"desc": "Ampicillin injection", "other": "", "strength": "500mg", "unit": "Vial", "price": 100},
            {"desc": "Analgesic Rub-in Balm", "other": "Nauma", "strength": "20gm", "unit": "Tube", "price": 100},
            {"desc": "Antacid gel", "other": "Relcer gel", "strength": "", "unit": "bottle", "price": 400},
            {"desc": "Antacid mixture/Allugel", "other": "Magnesium Trisilicate", "strength": "", "unit": "100ml", "price": 100},
            {"desc": "Anti-Asthmatic syrup", "other": "Franol", "strength": "", "unit": "100ml", "price": 100},
            {"desc": "Antibiotic ointment", "other": "Grabacin", "strength": "", "unit": "tube", "price": 200},
            {"desc": "Anti-diarrhoea tablets", "other": "Loperamide", "strength": "", "unit": "dose", "price": 100},
            {"desc": "Anti-haemorrhoidal cream/ointment", "other": "", "strength": "15gm", "unit": "Tube", "price": 400},
            {"desc": "Anti-haemorrhoidal suppositories", "other": "", "strength": "", "unit": "1 suppository", "price": 70},
            {"desc": "Anti-Snake venom", "other": "", "strength": "10ml", "unit": "vial", "price": 12000},
            {"desc": "Anti-Rabies vaccine", "other": "", "strength": "", "unit": "vial", "price": 1500},
            {"desc": "Throat Lozenges", "other": "", "strength": "", "unit": "dose", "price": 150},
            {"desc": "Artemether inj.", "other": "", "strength": "40mg/ml", "unit": "amp", "price": 150},
            {"desc": "Artemether/Lumefantrin tablets", "other": "AL", "strength": "20/120mg", "unit": "6 tabs", "price": 100},
            {"desc": "Artemether/Lumefantrin tablets", "other": "AL", "strength": "20/120mg", "unit": "12 tabs", "price": 200},
            {"desc": "Artemether/Lumefantrin tablets", "other": "AL", "strength": "20/120mg", "unit": "18 tabs", "price": 300},
            {"desc": "Artemether/Lumefantrin tablets", "other": "AL", "strength": "20/120mg", "unit": "24 tabs", "price": 400},
            {"desc": "Artesunate injection", "other": "", "strength": "60mg", "unit": "Vial", "price": 500},
        ]

        # Get or create the main category for these items
        category, _ = InventoryCategory.objects.get_or_create(
            name='Pharmaceuticals',
            defaults={'description': 'Prescription and over-the-counter drugs'}
        )

        def infer_formulation(desc):
            desc_lower = desc.lower()
            if 'tablet' in desc_lower or 'lozenge' in desc_lower or 'charcoal' in desc_lower:
                return 'Tablet'
            if 'capsule' in desc_lower:
                return 'Capsule'
            if 'syrup' in desc_lower or 'suspension' in desc_lower or 'mixture' in desc_lower or 'gel' in desc_lower:
                return 'Syrup'
            if 'injection' in desc_lower or 'inj' in desc_lower or 'vaccine' in desc_lower or 'venom' in desc_lower:
                return 'Injection'
            if 'infusion' in desc_lower:
                return 'Infusion'
            if 'ointment' in desc_lower or 'balm' in desc_lower or 'cream' in desc_lower:
                return 'Ointment'
            if 'drop' in desc_lower:
                return 'Drops'
            if 'inhaler' in desc_lower:
                return 'Inhaler'
            # Default to Tablet if unsure for this specific list, or guess based on unit
            return 'Tablet'

        count = 0
        try:
            with transaction.atomic():
                for item_data in drug_data:
                    # Construct descriptive name
                    name_parts = [item_data['desc']]
                    if item_data['other']:
                        name_parts.append(f"({item_data['other']})")
                    if item_data['strength']:
                        name_parts.append(item_data['strength'])
                    
                    full_name = " ".join(name_parts)
                    
                    # Create or get the InventoryItem
                    inventory_item, created = InventoryItem.objects.get_or_create(
                        name=full_name,
                        defaults={
                            'category': category,
                            'dispensing_unit': item_data['unit'],
                            'is_dispensed_as_whole': False,
                            'selling_price': item_data['price'],
                            'buying_price': 0,
                            'reorder_level': 10
                        }
                    )
                    
                    # Also create or update the Medication profile
                    generic = item_data['desc'].split(' ')[0] # rough guess for generic
                    formulation = infer_formulation(item_data['desc'] + " " + item_data['unit'])
                    
                    Medication.objects.get_or_create(
                        item=inventory_item,
                        defaults={
                            'generic_name': item_data['desc'],
                            'formulation': formulation
                        }
                    )
                    
                    if created:
                        count += 1
                        self.stdout.write(f"Added: {full_name}")

            self.stdout.write(self.style.SUCCESS(f'Successfully loaded {count} new drugs into inventory!'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to load drugs: {str(e)}'))

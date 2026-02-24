import os

drugs = [
    ("Salbutamol tablets", "Ventolin", "4mg", "dose", 100, True),
    ("Saline nasal drops", "", "0.9%", "10ml", 150, True),
    ("Secnidazole tablets", "", "500mg", "dose", 200, True),
    ("Silver sulphadiazine cream", "Burns cream", "1%", "15gm", 100, True),
    ("Silver sulphadiazine cream", "Burns cream", "1%", "250gm", 400, True),
    ("Silver sulphadiazine cream", "Burns cream", "1%", "100gm", 250, True),
    ("Spironolactone tabs", "Aldactone", "25mg", "Dose", 200, True),
    ("Sodium bicarbonate injection", "NaHCO3", "8.4", "10ml", 200, True),
    ("Tetracycline eye ointment", "", "1%3.5gm", "Tube", 100, True),
    ("Tetracycline skin ointment", "", "15gm", "Tube", 100, True),
    ("Tinidazole tablets", "", "500mg", "Per tab", 20, True),
    ("Tramadol caps", "", "50mg", "Dose", 200, True),
    ("Tramadol injection", "", "100mg", "Amp", 200, True),
    ("Vitamin B Complex tablets", "Tribex", "", "Per tab", 20, True),
    ("Vitamin B Complex injection", "", "", "Vial", 200, True),
    ("Vitamin B Compound tablets", "", "", "Dose", 100, True),
    ("Vitamin B12 injection", "Vit B12", "", "Amp", 500, True),
    ("Vitamin K1 injection", "Vit K", "10mg/ml", "Amp", 300, True),
    ("Vitamin K1 injection/oral", "Vit K1", "2mg/0.2ml", "Amp", 250, True),
    ("Zinc oxide ointment", "", "15%", "500gm", 400, True),
    ("Zinc tablets", "Znso4", "20mg", "dose", 150, True),
    ("Metroinidazole/Diloxamide", "Dyrade M", "250:200mg", "dose", 350, True),
    ("Metformin tabs", "", "500mg", "Per Tab", 20, True),
    ("Metformin tablets", "", "850mg", "Per tab", 25, True),
    ("Multivitamin syrup", "M/vit", "", "100ml", 100, True),
    ("Multivitamin tablets", "M/vit", "", "Dose", 100, True),
    ("Nalidixic acid tablets", "", "500mg", "Per tab", 10, True),
    ("Nifedipine retard tablets", "Adalat", "20mg", "dose", 200, True),
    ("Nitrofurantoin tablets", "", "100mg", "Dose", 100, True),
    ("Norfloxacin tablets", "", "400mg", "Dose", 250, True),
    ("Nystatin oral drops", "", "", "30ml", 100, True),
    ("Omeprazole capsules", "", "20mg", "Per dose", 200, True),
    ("Oral rehydration salts", "ORS", "500ml", "Dose", 100, True),
    ("Oxytocin injection", "Syntocinon", "10iu/ml", "Amp", 200, True),
    ("Paracetamol injection", "PCM", "150mg/ml", "Amp", 300, True),
    ("Paracetamol junior tablets", "PCM", "100mg", "Dose", 100, True),
    ("Paracetamol suppositories", "PCM", "250mg", "Per suppository", 20, True),
    ("Paracetamol suppositories", "PCM", "125mg", "Per supp.", 20, True),
    ("Paracetamol syrup", "PCM", "120mg/5ml", "60ml", 100, True),
    ("Paracetamol tablets", "PCM", "500mg", "Dose", 100, True),
    ("Penicillin benzathine injection", "Benzathine", "2.4mu", "Vial", 150, True),
    ("Penicillin benzyl injection", "x-pen", "1mu", "Vial", 100, True),
    ("Penicillin procaine fortified inj", "PPF", "4mu", "Vial", 200, True),
    ("Penicillin V. suspension", "Pen-V", "125mg/5ml", "100ml", 100, True),
    ("Penicillin V. tablets", "", "250mg", "dose", 400, True),
    ("Pethidine injection", "", "50mg/ml", "Amp", 300, True),
    ("Pethidine injection", "", "100mg/2ml", "Amp", 300, True),
    ("Phenobarbitone tablets", "", "30mg", "Dose", 200, True),
    ("Phenobarbitone tablets", "", "200mg", "Amp", 500, True),
    ("Phenobarbitone inj.", "", "", "amp", 500, True),
    ("Potassium chloride injection", "", "15%", "Amp", 200, True),
    ("Povidone-iodine mouth wash", "", "1%w/v", "250ml", 200, True),
    ("Prednisolone eye drops", "", "1%", "10ml", 100, True),
    ("Prednisolone tablets", "", "5mg", "Dose", 100, True),
    ("Progesterone", "Susten", "200mg", "Per Capsule", 200, True),
    ("Promethazine injection", "", "50mg/2ml", "Amp", 100, True),
    ("Promethazine syrup", "", "5mg/5ml", "60ml", 100, True),
    ("Promethazine tablets", "", "25mg", "dose", 100, True),
    ("Quinine drops", "", "20%w/v", "15ml", 200, True),
    ("Quinine injection", "", "600mg/2ml", "Amp", 150, True),
    ("Quinine tabs", "", "600mg", "dose", 400, True),
    ("Quinine tablets", "", "300mg", "dose", 200, True),
    ("Ranitidine injection", "Zantac", "50mg/2ml", "Amp", 150, True),
    ("Ranitidine tablets", "Zantac", "300mg", "dose", 200, True),
    ("Ranitidine tablets", "zantac", "150mg", "dose", 100, True),
    ("Salbutamol inhaler", "Ventolin", "100mg", "pack", 400, True),
    ("Salbutamol syrup", "Ventolin", "2mg/5ml", "100ml", 100, True),
    ("Flucloxacillin capsules", "Fluxapen", "500mg", "Dose", 400, True),
    ("Flucloxacillin injection", "Fluzapen", "500mg", "Vial", 200, True),
    ("Fluconazole tablets", "", "50mg", "Per Tab", 10, True),
    ("Fluconazole tablets", "", "200mg", "Per Tab", 20, True),
    ("Fluphenazine decanoate injection", "", "25mg/ml", "1ml Amp", 250, True),
    ("Fluoxetine tabs", "Modicate", "20mg", "Dose", 200, True),
    ("Folic acid tabs", "", "5mg", "Dose", 100, True),
    ("Frusemide injection", "Lasix", "20mg/2ml", "Amp", 100, True),
    ("Frusemide tablets", "Lasix", "40mg", "dose", 100, True),
    ("Gentamycin eye drops", "", "0.3%", "5ml", 100, True),
    ("Gentamycin Adult inj", "", "80mg/2ml", "", 100, True),
    ("Gentamycin Paeds inj", "", "20mg/2ml", "", 100, True),
    ("Glibenclamide tablets", "", "5mg", "Dose-30pack", 300, True),
    ("Griseofulvin tablets", "", "250mg", "1 tab", 10, True),
    ("H Pylori kit", "", "", "dose", 2000, True),
    ("Haematinic capsules", "Ranferon", "", "dose", 150, True),
    ("Haematinic syrup", "Ranferon", "200ml", "Bottle", 500, True),
    ("Heparin injection", "", "5,000iu/ml", "5ml vial", 600, True),
    ("Hydralazine injection", "Apresoline", "20mg/ml", "1ml Amp", 900, True),
    ("Hydrochlorthiazide tablets", "HCT", "50mg", "Dose", 200, True),
    ("Hydrochlorthiazide tablets", "HCT", "25mg", "Dose", 100, True),
    ("Hydrocortisone cream", "", "1%", "15gm/tube", 100, True),
    ("Hydrocortisone injection", "", "100mg", "Vial", 200, True),
    ("Hyoscine Butylbromide injection", "Buscopan", "20mg/ml", "Amp", 100, True),
    ("Hyoscine Butylbromide tablets", "Buscopan", "10mg", "dose", 150, True),
    ("Ibuprofen suspension", "Bruffen", "100mg/5ml", "100ml", 100, True),
    ("Ibuprofen tablets", "Bruffen", "200mg", "Dose", 100, True),
    ("Ibuprofen tablets", "Bruffen", "400mg", "Dose", 100, True),
    ("Indomethacin capsules", "Indocid", "25mg", "Dose", 200, True),
    ("Insulin (Actrapid) injection", "", "100iu/ml", "10ml", 500, True),
    ("Insulin (Mixtard) injection 30/70", "", "100iu/ml", "10ml", 500, True),
    ("Ketamine injection", "", "50mg/ml", "10ml", 400, True),
    ("Ketoconazole tablets", "", "200mg", "Per tab", 10, True),
    ("Levofloxacin tablets", "L-floxacin", "500mg", "dose", 800, True),
    ("Loperamide tablets", "Immodium", "2mg", "dose", 100, True),
    ("Magnesium sulfate injection", "Mgs04", "50%", "Vial", 500, True),
    ("Mebendazole syrup", "Vermox", "100mg/5ml", "dose", 100, True),
    ("Mebendazole tabs", "", "", "Dose", 100, True),
    ("Meloxicam tablets", "", "7.5mg", "dose", 100, True),
    ("Methyldopa tablets", "Aldomet", "250mg", "Per tab", 20, True),
    ("Metoclopramide injection", "Plasil", "10mg/2ml", "Amp", 100, True),
    ("Metoclopramide tablets", "Plasil", "10mg", "dose", 100, True),
    ("Metronidazole injection", "Flagyl", "500mg/100ml", "100ml", 200, True),
    ("Metronidazole suspension", "Flagyl", "200mg/5ml", "100ml/bottle", 100, True),
    ("Metronidazole tablets", "Flagyl", "200mg", "Dose", 100, True),
    ("Metronidazole tablets", "Flagyl", "400mg", "Dose", 100, True),
    ("Misoprostol", "Cytotec", "200mcg", "Per tab", 5, True),
    ("Ascorbic Acid tablets", "", "200mg", "Dose", 100, True),
    ("Aspirin Cardiac tablets", "Ascard", "75mg", "Dose", 100, True),
    ("Aspirin tablets", "ASA", "300mg", "Dose", 100, True),
    ("Atenolol tablets", "", "50mg", "Dose/30", 300, True),
    ("Atropine injection", "", "1mg/ml", "Amp", 200, True),
    ("Azithromycin suspension", "", "200mg/5ml", "bottle", 150, True),
    ("Azithromycin tablets", "", "250mg", "Dose", 150, True),
    ("Azithromycin tablets", "", "500mg", "Dose", 300, True),
    ("Artovastatin tablets", "", "10mg", "dose", 200, True),
    ("Arttovastatin tablets", "", "20mg", "dose", 300, True),
    ("Benzhexol tablets", "Artane", "5mg", "dose", 200, True),
    ("Benzyl Benzoat emulsion", "", "", "", 100, True),
    ("Betamethasone cream", "", "0.1%", "1 tube", 100, True),
    ("Betamethasone/Neomycin drops", "", "0.1/035%w/v", "7.5ml", 150, True),
    ("Bisacodyl tabs", "", "5mg", "dose", 100, True),
    ("Boric Acid Ear Drops", "", "1.83%w/v", "10ml", 100, True),
    ("Bromocriptine tablets", "", "2.5mg", "Per tab", 50, True),
    ("Bronchodilator with mucolytic", "Trimex", "", "100ml", 300, True),
    ("Calamine lotion", "", "", "100ml", 250, True),
    ("Calcium gluconate injection", "", "10%", "10ml/Amp", 300, True),
    ("Carbamazepine tablets", "", "200mg", "Dose", 200, True),
    ("Carvedilol tablets", "", "6.25mg", "30/dose", 250, True),
    ("Cefixine tablets", "", "200mg", "Dose", 500, True),
    ("Cefixine tablets", "", "400mg", "Dose", 750, True),
    ("Cefriaxone injection (Generic) IV/IM", "", "250mg", "vial", 150, True),
    ("Cefriaxone injection (Generic) IV/IM", "", "1gm", "vial", 300, True),
    ("Cefriaxone injection (Rocephine) IV", "Original", "1gm", "vial", 2000, True),
    ("Cefriaxone injection (Rocephine) IV", "Original", "250mg", "vial", 1000, True),
    ("Cefuroxime tabs", "Zinnat", "250mg", "dose", 500, True),
    ("Cefuroxime tabs", "Zinnat", "500mg", "dose", 750, True),
    ("Cephalexin capsules", "", "250mg", "Dose", 200, True),
    ("Cephalexin capsules", "", "500mg", "Dose", 400, True),
    ("Cephalexin suspension", "", "125mg/5ml", "100ml", 200, True),
    ("Cetrizine syrup", "", "5mg/5ml", "60ml/bottle", 100, True),
    ("Cetrizine tablets", "", "10mg", "Dose", 100, True),
    ("Chloramphenicol eye drops", "CAF", "0.5%", "10ml", 100, True),
    ("Chloramphenicol injection", "CAF", "1gm", "Vial", 150, True),
    ("Chloramphenicol suspension", "CAF", "125mg/5ml", "100ml", 100, True),
    ("Chlopheniramine injection", "Piriton", "10mg/ml", "Amp", 100, True),
    ("Chlopheniramine tablets", "Piriton", "4mg", "dose", 100, True),
    ("Chlopheniramine suspension", "Piriton", "2mg/5ml", "60ml/bottle", 100, True),
    ("Chlorpromazine tablets", "Largactil", "25mg", "dose", 100, True),
    ("Ciprofloxacin capsules", "Cipro", "500mg", "Dose", 200, True),
    ("Cimetidine tabs", "", "400mg", "dose", 400, True),
    ("Clotrimazole cream", "", "1%", "20gm Tube", 100, True),
    ("Clotrimazole pessaries", "", "200mg", "3/dose", 100, True),
    ("Clotrimazole/Betamethasone cream", "", "1%/0.1%w/w", "tube", 150, True),
    ("Cloxacillin", "", "500mg", "Dose", 250, True),
    ("Cloxacillin", "", "250mg", "Dose", 150, True),
    ("Cloxacillin syrup", "", "", "Bottle", 100, True),
    ("Cold capsules", "", "", "Dose", 100, True),
    ("Cotton wool", "", "50g", "piece", 150, False),
    ("Cotton wool", "", "100g", "piece", 300, False),
    ("Cotton woo", "", "400g", "piece", 400, False),
    ("Co-otrimaxazole suspension", "Septrine", "200/40mg", "100ml", 100, True),
    ("Co-otrimaxazole tablets", "Septrine", "400/80mg", "Dose", 200, True),
    ("Cotrimoxazole tabs", "", "800/160mg", "dose", 400, True),
    ("Cough expectorant mixture", "C/Exp", "", "100ml", 100, True),
    ("Cough suppressant mixture", "C/Supp", "", "100ml", 100, True),
    ("Dexamethasone/Gentamycin eye drops", "Gendex", "0.1/0.3%w/v", "5ml", 150, True),
    ("Dexamethasone injection", "", "4mg", "Amp", 200, True),
    ("Dextrose injection", "", "50%, 10%, 5%", "50ml", 200, True),
    ("Dextrose 5% in normal saline", "", "5%/0.09%W/V", "500ml", 300, True),
    ("Diazepam injection", "Valium", "10mg/2ml", "Amp", 200, True),
    ("Diazepam suppositories", "", "2.5mg", "Per suppository", 50, True),
    ("Diazepam tablets", "", "5mg", "dose", 100, True),
    ("Diclofenac sodium tablets", "", "50mg", "dose", 100, True),
    ("Diclofenac/paracetamol/chlorzoxanone tablets", "Flamoryl/Flamchek", "50/325/250mg", "Per tab", 20, True),
    ("Diclofenac Gel", "", "1%w/w", "tube", 100, True),
    ("Diclofenac injection", "", "25mg/ml", "3ml Amp", 100, True),
    ("Digoxin tablets", "", "0.25mg", "Per tab", 20, True),
    ("Doxycycline capsule", "Doxy", "100mg", "Dose", 150, True),
    ("Dopamine injection", "", "40mg/ml", "amp", 500, True),
    ("Domperidone", "Deflux", "100ml", "Bottle", 400, True),
    ("Domperidone tablet", "Deflux", "10mg", "Dose", 200, True),
    ("Enalapril tablets", "", "5mg", "Dose/30", 300, True),
    ("Ephedrine nasal drops", "", "0.5%", "10/15ml", 100, True),
    ("Ephedrine nasal drops", "", "1.0%", "10/15ml", 150, True),
    ("Erthromycin suspension", "", "125mg/5ml", "100ml", 150, True),
    ("Erthromycin tablets", "", "250mg", "Dose", 200, True),
    ("Erthromycin tablets", "", "500mg", "Dose", 400, True),
    ("Esomeprazole", "", "20mg", "Cap", 30, True),
    ("Ferrous sulphate tablets", "Feso4", "200mg", "Dose", 100, True),
    ("Ferrous sulphate/VitB comp syrup", "Feso4", "100/1.5/1/0/2.0/5.0mg per 5ml", "100ml/Bottle", 100, True),
    ("Ferrous/Folic acid tablets", "", "350mg", "Dose", 100, True),
    ("Flucloxacillin capsules", "Fluxapen", "250mg", "Dose", 300, True),
    ("Crepe bandages", "", "All sizes", "Per piece", 300, False),
    ("Speculum vaginal disposable", "", "All sizes", "piece", 300, False),
    ("Plaster of Paris bandage", "POP", "All sizes", "Per each", 400, False),
    ("Catheters", "", "All sizes", "Each", 200, False),
    ("Chest drainage tube", "", "All sizes", "Each", 1500, False),
    ("Endotrachael tubes", "", "All sizes", "Each", 300, False),
    ("Naso-gastric tubes", "NGT", "All sizes", "Each", 100, False),
    ("Sunction tubes", "", "All sizes", "Each", 200, False),
    ("Surgical blades", "", "All sizes", "Each", 50, False),
    ("Blood giving set", "", "Set", "Each", 200, False),
    ("Maternity pads", "", "1 pkt", "Each", 200, False),
    ("Thermometer (Centigrade)", "", "Piece", "Each", 100, False),
    ("Umbilical cord clamps", "", "Piece", "Each", 100, False),
    ("Urine bags with outlet", "", "Piece", "Each", 100, False),
    ("Gloves sterile/surgical", "", "All sizes", "Each", 100, False),
    ("IV cannula", "", "All sizes", "", 200, False),
    ("IV giving set", "", "All sizes", "", 200, False),
    ("Syringe + Needles", "2 - 20cc", "Piece", "Each", 20, False),
    ("Syringes", "", "50/60cc", "Piece", 200, False),
    ("Syringes disposable (Insulin)", "", "Piece", "", 20, False),
    ("Chromic catcut", "", "All sizes", "", 500, False),
    ("Vicryl suture", "", "All sizes", "", 1000, False),
]

command_script = f"""import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from inventory.models import InventoryItem, InventoryCategory, Medication, ConsumableDetail, DrugClass

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Load all drugs and supplies from extracted lists into the inventory'

    def handle(self, *args, **kwargs):
        # We process the already mapped items
        pharma_cat, _ = InventoryCategory.objects.get_or_create(
            name='Pharmaceuticals',
            defaults={{'description': 'Prescription and over-the-counter drugs'}}
        )

        supply_cat, _ = InventoryCategory.objects.get_or_create(
            name='Medical Supplies',
            defaults={{'description': 'Consumables, sutures, bandages'}}
        )

        def infer_formulation(desc):
            desc_lower = desc.lower()
            if 'tablet' in desc_lower or 'lozenge' in desc_lower or 'charcoal' in desc_lower or 'tab' in desc_lower:
                return 'Tablet'
            if 'capsule' in desc_lower or 'cap' in desc_lower:
                return 'Capsule'
            if 'syrup' in desc_lower or 'suspension' in desc_lower or 'mixture' in desc_lower or 'gel' in desc_lower or 'lotion' in desc_lower or 'emulsion' in desc_lower or 'oral' in desc_lower:
                return 'Syrup'
            if 'injection' in desc_lower or 'inj' in desc_lower or 'vaccine' in desc_lower or 'venom' in desc_lower:
                return 'Injection'
            if 'infusion' in desc_lower or 'dextrose' in desc_lower:
                return 'Infusion'
            if 'ointment' in desc_lower or 'balm' in desc_lower or 'cream' in desc_lower:
                return 'Ointment'
            if 'drop' in desc_lower:
                return 'Drops'
            if 'inhaler' in desc_lower:
                return 'Inhaler'
            return 'Tablet'

        count_meds = 0
        count_supps = 0

        # list of tuples: (desc, other, strength, unit, price, is_medicine)
        items = {repr(drugs)}

        try:
            with transaction.atomic():
                for desc, other, strength, unit, price, is_medicine in items:
                    name_parts = [desc]
                    if other:
                        name_parts.append(f"({{other}})")
                    if strength:
                        name_parts.append(strength)
                    
                    full_name = " ".join(name_parts)
                    category = pharma_cat if is_medicine else supply_cat
                    unit_pack = unit if unit else "Piece"
                    
                    inventory_item, created = InventoryItem.objects.get_or_create(
                        name=full_name,
                        defaults={{
                            'category': category,
                            'dispensing_unit': unit_pack,
                            'is_dispensed_as_whole': not is_medicine,
                            'selling_price': price,
                            'buying_price': 0,
                            'reorder_level': 10
                        }}
                    )
                    
                    if is_medicine:
                        formulation = infer_formulation(desc + " " + unit)
                        Medication.objects.get_or_create(
                            item=inventory_item,
                            defaults={{
                                'generic_name': desc,
                                'formulation': formulation
                            }}
                        )
                        if created:
                            count_meds += 1
                    else:
                        ConsumableDetail.objects.get_or_create(
                            item=inventory_item,
                            defaults={{
                                'material': 'Medical Grade',
                                'is_sterile': 'sterile' in desc.lower() or 'injection' in desc.lower(),
                                'size': strength if strength else 'Standard'
                            }}
                        )
                        if created:
                            count_supps += 1
                            
                    if created:
                        self.stdout.write(f"Added: {{full_name}} (Med={{is_medicine}})")

            self.stdout.write(self.style.SUCCESS(f'Successfully loaded {{count_meds}} new medications and {{count_supps}} new supplies!'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to load drugs: {{str(e)}}'))
"""

with open('/home/kali/Downloads/hms/inventory/management/commands/load_all_inventory.py', 'w') as f:
    f.write(command_script)
print("done")

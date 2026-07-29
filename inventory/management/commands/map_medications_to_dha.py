"""
Map local Medication rows to DHA HPT GE* generic products.

Usage:
  python manage.py map_medications_to_dha --dry-run
  python manage.py map_medications_to_dha --only-unmapped
  python manage.py map_medications_to_dha --apply --sync-item-name
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from inventory.dha_align import apply_dha_generic_product
from inventory.models import Medication
from home.dha_medication import suggest_dha_for_local_drug


class Command(BaseCommand):
    help = "Suggest/apply DHA HPT GE* codes onto local Medication records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show suggestions without saving (default if --apply not set).",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist auto-selected GE* matches onto Medication.",
        )
        parser.add_argument(
            "--only-unmapped",
            action="store_true",
            help="Skip medications that already have generic_concept_code.",
        )
        parser.add_argument(
            "--sync-item-name",
            action="store_true",
            help="When applying, set InventoryItem.name to the DHA FSN.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max medications to process (0 = all).",
        )

    def handle(self, *args, **options):
        apply = bool(options["apply"])
        sync_name = bool(options["sync_item_name"])
        qs = Medication.objects.select_related("item", "drug_class").order_by("generic_name")
        if options["only_unmapped"]:
            qs = qs.filter(Q(generic_concept_code="") | Q(generic_concept_code__isnull=True))
        if options["limit"]:
            qs = qs[: options["limit"]]

        mapped = skipped = failed = 0
        for med in qs:
            suggestion = suggest_dha_for_local_drug(
                name=med.item.name if med.item_id else "",
                generic_name=med.generic_name or "",
                formulation=med.formulation or "",
            )
            suggested = suggestion.get("suggested")
            auto = bool(suggestion.get("auto_selected"))
            code = (suggested or {}).get("code")
            title = (suggested or {}).get("title")

            if not suggested or not code:
                failed += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"NO MATCH  {med.item_id} {med.generic_name!r} / {med.item.name!r}"
                    )
                )
                continue

            status = "AUTO" if auto else "CANDIDATE"
            self.stdout.write(
                f"{status:9} item={med.item_id} {med.generic_name!r} "
                f"-> {code} {title}"
            )

            if not apply:
                skipped += 1
                continue
            if not auto:
                skipped += 1
                continue

            apply_dha_generic_product(
                med,
                code=code,
                title=title or "",
                enrich=True,
                sync_item_name=sync_name,
            )
            if sync_name and med.item_id:
                med.item.save(update_fields=["name"])
            med.save()
            mapped += 1

        mode = "APPLIED" if apply else "DRY-RUN"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: mapped={mapped} skipped={skipped} no_match={failed}"
            )
        )

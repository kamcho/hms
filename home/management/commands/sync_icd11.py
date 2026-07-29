from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from home.icd11_local import (
    download_tabulation_bytes,
    import_tabulation_from_bytes,
    local_icd11_count,
    tabulation_zip_url,
    import_tabulation_rows,
)


class Command(BaseCommand):
    help = (
        'Import WHO ICD-11 MMS Simple Tabulation into the local database for offline search. '
        'No API credentials required.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--release',
            default=settings.ICD11_RELEASE,
            help='ICD-11 release id (default: ICD11_RELEASE setting).',
        )
        parser.add_argument(
            '--linearization',
            default=settings.ICD11_LINEARIZATION,
            help='Linearization name (default: mms).',
        )
        parser.add_argument(
            '--language',
            default=settings.ICD11_LANGUAGE,
            help='Tabulation language code (default: ICD11_LANGUAGE setting).',
        )
        parser.add_argument(
            '--file',
            help='Path to a local SimpleTabulation .zip or .txt file instead of downloading.',
        )
        parser.add_argument(
            '--url',
            help='Override WHO tabulation download URL.',
        )
        parser.add_argument(
            '--keep-existing',
            action='store_true',
            help='Append without deleting existing rows for this release/linearization.',
        )

    def handle(self, *args, **options):
        release = options['release']
        linearization = options['linearization']
        language = options['language']
        clear_existing = not options['keep_existing']

        if options['file']:
            path = Path(options['file'])
            if not path.exists():
                raise CommandError(f'File not found: {path}')
            if path.suffix.lower() == '.zip':
                data = path.read_bytes()
                imported, skipped = import_tabulation_from_bytes(
                    data,
                    release=release,
                    linearization=linearization,
                    clear_existing=clear_existing,
                )
            elif path.suffix.lower() == '.txt':
                rows = []
                with path.open(encoding='utf-8-sig', newline='') as handle:
                    import csv

                    reader = csv.DictReader(handle, delimiter='\t')
                    for row in reader:
                        rows.append({str(k).strip(): (v or '').strip() for k, v in row.items() if k})
                imported, skipped = import_tabulation_rows(
                    rows,
                    release=release,
                    linearization=linearization,
                    clear_existing=clear_existing,
                )
            else:
                raise CommandError('Supported file types: .zip (WHO release archive) or .txt tabulation.')
        else:
            url = options['url'] or tabulation_zip_url(release=release, language=language)
            self.stdout.write(f'Downloading ICD-11 tabulation from {url} ...')
            data = download_tabulation_bytes(url=url)
            imported, skipped = import_tabulation_from_bytes(
                data,
                release=release,
                linearization=linearization,
                clear_existing=clear_existing,
            )

        total = local_icd11_count(release=release, linearization=linearization)
        self.stdout.write(self.style.SUCCESS(
            f'ICD-11 sync complete: imported {imported} rows ({skipped} skipped). '
            f'{total} codes now stored for {release}/{linearization}.'
        ))

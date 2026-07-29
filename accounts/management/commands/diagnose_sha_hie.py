from django.core.management.base import BaseCommand

from accounts.sha_diagnostics import format_sha_diagnostics_report, run_sha_connectivity_diagnostics


class Command(BaseCommand):
    help = (
        'Run AfyaLink UAT connectivity checks and print a report you can email to DHA '
        '(afyaconnect.dha@gmail.com) when the support portal is unavailable.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--sample-id',
            default='2897398',
            help='National ID to use for eligibility/CR probe (default: AfyaLink doc example).',
        )
        parser.add_argument(
            '--id-type',
            default='National ID',
            help='Identification type for probes.',
        )
        parser.add_argument(
            '--output',
            help='Optional path to save the text report (e.g. docs/sha_uat_report.txt).',
        )

    def handle(self, *args, **options):
        data = run_sha_connectivity_diagnostics(
            sample_id=options['sample_id'],
            identification_type=options['id_type'],
        )
        report = format_sha_diagnostics_report(data)

        if options['output']:
            with open(options['output'], 'w', encoding='utf-8') as handle:
                handle.write(report)
            self.stdout.write(self.style.SUCCESS(f'Report saved to {options["output"]}'))

        self.stdout.write(report)

        if data.get('auth_ok') and not data.get('eligibility_ok'):
            self.stdout.write(self.style.WARNING(
                '\nEligibility endpoint failed while auth succeeded — likely UAT outage (HTTP 522).'
            ))
        elif data.get('auth_ok') and data.get('eligibility_ok'):
            self.stdout.write(self.style.SUCCESS('\nAll checks passed.'))

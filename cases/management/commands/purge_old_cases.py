from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from cases.models import Case, CaseStatus, SmsInbound


class Command(BaseCommand):
    help = (
        "Data minimisation: permanently delete CLOSED cases (and their audit trail) older than N "
        "days, plus inbound SMS older than N days. Run from cron. Use --dry-run first."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        cases = Case.objects.filter(status=CaseStatus.CLOSED, updated_at__lt=cutoff)
        sms = SmsInbound.objects.filter(received_at__lt=cutoff)
        self.stdout.write(f"{cases.count()} closed cases and {sms.count()} SMS older than {opts['days']} days")
        if opts["dry_run"]:
            self.stdout.write("dry run: nothing deleted")
            return
        cases.delete()
        sms.delete()
        self.stdout.write(self.style.SUCCESS("deleted"))

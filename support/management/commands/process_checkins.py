from django.core.management.base import BaseCommand

from support.alerts import alert_unassigned, escalate_sos, process_checkins


class BaseRun(BaseCommand):
    help = "Run every minute: check-in alerts, SOS escalation, unassigned-case alerts."

    def handle(self, *a, **k):
        self.stdout.write(
            f"checkins={process_checkins()} escalations={escalate_sos()} unassigned={alert_unassigned()}"
        )


Command = BaseRun

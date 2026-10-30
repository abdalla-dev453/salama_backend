from django.core.management.base import BaseCommand

from extras.models import HelpContact

# Only the national numbers the app already relies on. Local clinics, police desks and
# safe houses must be added by Utetezi in Django admin once they are verified.
NATIONAL = [
    dict(name="National GBV helpline", category="helpline", phone="1195", hours="24 hours",
         notes_en="Free call.", notes_sw="Simu ya bure.", sort_order=1),
    dict(name="Emergency (police, ambulance)", category="helpline", phone="999", phone_alt="112",
         hours="24 hours", notes_en="Life in danger.", notes_sw="Maisha yako hatarini.", sort_order=2),
    dict(name="Childline Kenya", category="helpline", phone="116", hours="24 hours",
         notes_en="For children. Free call.", notes_sw="Kwa watoto. Simu ya bure.", sort_order=3),
]


class Command(BaseCommand):
    help = "Adds the national helplines (idempotent). Add local contacts in Django admin."

    def handle(self, *args, **opts):
        for row in NATIONAL:
            _, created = HelpContact.objects.get_or_create(name=row["name"], defaults=row)
            self.stdout.write(("added " if created else "exists ") + row["name"])

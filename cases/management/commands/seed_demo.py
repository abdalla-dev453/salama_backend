import secrets

from django.core.management.base import BaseCommand

from accounts.models import User

CHWS = [
    ("CHW-KWALE-001", "Fatuma", "Ukunda"),
    ("CHW-KWALE-002", "Ali", "Msambweni"),
    ("CHW-KWALE-003", "Mwanaisha", "Lunga Lunga"),
    ("CHW-KWALE-004", "Hassan", "Kinango"),
]


class Command(BaseCommand):
    help = "Create the four Kwale CHW accounts (random passwords, printed ONCE) if they do not exist."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Use this password for all new CHWs (testing only).")

    def handle(self, *args, **opts):
        for username, name, area in CHWS:
            if User.objects.filter(username__iexact=username).exists():
                self.stdout.write(f"exists   {username}")
                continue
            password = opts["password"] or secrets.token_urlsafe(9)
            user = User(username=username, full_name=f"{name} - {area}", area=area,
                        role=User.Role.CHW)
            user.set_password(password)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"created  {username}  password: {password}"))
        self.stdout.write("Give each CHW their password privately. Admin: python manage.py createsuperuser")

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.models import User
from cases.models import Case, CaseStatus, CaseType

PASSWORD = "Str0ng-pass-123"


def make_case(ref="KWALE-2610-AAAAAA", **kw):
    data = dict(
        case_ref=ref, type=CaseType.VIOLENCE, status=CaseStatus.NEW,
        description="secret description", location_text="Ukunda",
        reported_at=timezone.now(),
    )
    data.update(kw)
    return Case.objects.create(**data)


class BaseTest(APITestCase):
    def setUp(self):
        cache.clear()  # throttle counters live in the cache
        self.admin = User.objects.create_user(
            "admin", password=PASSWORD, role=User.Role.ADMIN, full_name="Admin Officer")
        self.fatuma = User.objects.create_user(
            "CHW-KWALE-001", password=PASSWORD, full_name="Fatuma", phone="+254712000001")
        self.ali = User.objects.create_user(
            "CHW-KWALE-002", password=PASSWORD, full_name="Ali", phone="+254712000002")

    def login(self, username, password=PASSWORD):
        r = APIClient().post("/api/auth/login/", {"username": username, "password": password},
                             format="json")
        return r

    def client_for(self, user):
        r = self.login(user.username)
        assert r.status_code == 200, r.content
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        return c

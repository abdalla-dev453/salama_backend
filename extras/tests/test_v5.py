from django.test import Client
from rest_framework.test import APIClient

from accounts.models import User
from cases.models import Case, CaseStatus, CaseType
from cases.tests.base import PASSWORD, BaseTest, make_case


class CreateCaseTests(BaseTest):
    def test_chw_creates_case_assigned_to_self(self):
        c = self.client_for(self.fatuma)
        r = c.post("/api/new-case/", {
            "type": "violence", "description": "seen at the clinic", "location_text": "Ukunda",
            "contact_phone": "0712345678", "safe_to_call": True, "lat": -4.28, "lon": 39.57,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        case = Case.objects.get(case_ref=r.data["case_ref"])
        self.assertEqual(case.assigned_to, self.fatuma)
        self.assertEqual(case.updates.count(), 2)  # created + assigned
        self.assertEqual(case.contact_phone, "+254712345678")

    def test_validation_and_auth(self):
        c = self.client_for(self.fatuma)
        self.assertEqual(c.post("/api/new-case/", {"type": "violence"}, format="json").status_code, 400)
        self.assertEqual(c.post("/api/new-case/", {"type": "x", "description": "a"}, format="json").status_code, 400)
        r = APIClient().post("/api/new-case/", {"type": "violence", "description": "a"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_two_creations_make_two_cases(self):
        c = self.client_for(self.fatuma)
        body = {"type": "care", "description": "x", "location_text": "Kinango"}
        a = c.post("/api/new-case/", body, format="json").data["case_ref"]
        b = c.post("/api/new-case/", body, format="json").data["case_ref"]
        self.assertNotEqual(a, b)


class DashboardV5Tests(BaseTest):
    def admin_client(self):
        c = Client()
        c.force_login(self.admin)
        return c

    def setUp(self):
        super().setUp()
        for i in range(6):
            make_case(f"KWALE-2610-A0000{i}", location_text="Ukunda", lat=-4.28123 + i * 0.0001, lon=39.57456)
        make_case("SOS-AAAAAA", type=CaseType.SOS, status=CaseStatus.SOS, lat=-4.3, lon=39.5)

    def test_all_pages_load_for_admin(self):
        c = self.admin_client()
        for url in ["/dashboard/", "/dashboard/?days=7", "/dashboard/?days=90", "/dashboard/cases/",
                    "/dashboard/chws/", "/dashboard/analytics/", "/dashboard/settings/",
                    "/dashboard/search/?q=Ukunda"]:
            r = c.get(url)
            self.assertEqual(r.status_code, 200, url)

    def test_chw_forbidden_everywhere(self):
        c = Client()
        c.force_login(self.fatuma)
        for url in ["/dashboard/analytics/", "/dashboard/settings/", "/dashboard/search/?q=a", "/dashboard/chws/"]:
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_map_is_rounded_and_private(self):
        html = self.admin_client().get("/dashboard/").content.decode()
        self.assertNotIn("-4.28123", html)  # exact coordinates never reach the page
        self.assertIn("-4.28", html)
        self.assertNotIn("secret description", html)

    def test_bell_shows_unanswered_sos(self):
        html = self.admin_client().get("/dashboard/").content.decode()
        self.assertIn('<span class="n">1</span>', html)

    def test_search_finds_case_and_chw(self):
        c = self.admin_client()
        self.assertContains(c.get("/dashboard/search/?q=SOS-AAA"), "SOS-AAAAAA")
        self.assertContains(c.get("/dashboard/search/?q=Fatuma"), "CHW-KWALE-001")

    def test_create_toggle_and_reset_chw(self):
        c = self.admin_client()
        r = c.post("/dashboard/chws/", {"action": "create", "username": "chw-kwale-009", "full_name": "Zuhura",
                                        "phone": "0712000009", "area": "Kinango", "password": "Str0ng-pass-999"})
        self.assertEqual(r.status_code, 302)
        u = User.objects.get(username="CHW-KWALE-009")
        self.assertEqual((u.role, u.phone, u.area), ("chw", "+254712000009", "Kinango"))
        self.assertTrue(u.check_password("Str0ng-pass-999"))
        c.post("/dashboard/chws/", {"action": "toggle", "id": u.pk})
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        c.post("/dashboard/chws/", {"action": "password", "id": u.pk, "password": "An0ther-pass-777"})
        u.refresh_from_db()
        self.assertTrue(u.check_password("An0ther-pass-777"))

    def test_weak_password_and_duplicate_rejected(self):
        c = self.admin_client()
        c.post("/dashboard/chws/", {"action": "create", "username": "CHW-X-1", "password": "123"})
        self.assertFalse(User.objects.filter(username="CHW-X-1").exists())
        c.post("/dashboard/chws/", {"action": "create", "username": "chw-kwale-001", "password": "Str0ng-pass-999"})
        self.assertEqual(User.objects.filter(username__iexact="CHW-KWALE-001").count(), 1)

    def test_analytics_hides_small_cells(self):
        html = self.admin_client().get("/dashboard/analytics/").content.decode()
        self.assertIn("Ukunda", html)
        self.assertIn("&lt;5", html)  # the SOS cell (1 case) is hidden

from rest_framework.test import APIClient

from accounts.models import User

from .base import PASSWORD, BaseTest, make_case


class LoginTests(BaseTest):
    def test_login_returns_tokens_and_user(self):
        r = self.login("CHW-KWALE-001")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)
        self.assertEqual(r.data["user"]["username"], "CHW-KWALE-001")
        self.assertEqual(r.data["user"]["role"], "chw")
        self.assertNotIn("password", r.data["user"])

    def test_chw_id_is_case_insensitive(self):
        self.assertEqual(self.login("chw-kwale-001").status_code, 200)

    def test_wrong_password_and_unknown_user(self):
        self.assertEqual(self.login("CHW-KWALE-001", "nope").status_code, 401)
        self.assertEqual(self.login("CHW-NOBODY", PASSWORD).status_code, 401)

    def test_inactive_chw_cannot_login(self):
        self.fatuma.is_active = False
        self.fatuma.save()
        self.assertEqual(self.login("CHW-KWALE-001").status_code, 401)

    def test_deactivated_chw_loses_access_with_existing_token(self):
        c = self.client_for(self.fatuma)
        self.assertEqual(c.get("/api/cases/").status_code, 200)
        self.fatuma.is_active = False
        self.fatuma.save()
        self.assertEqual(c.get("/api/cases/").status_code, 401)

    def test_me(self):
        r = self.client_for(self.fatuma).get("/api/auth/me/")
        self.assertEqual(r.data["full_name"], "Fatuma")
        self.assertEqual(APIClient().get("/api/auth/me/").status_code, 401)

    def test_refresh(self):
        login = self.login("CHW-KWALE-001")
        r = APIClient().post("/api/auth/refresh/", {"refresh": login.data["refresh"]}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertEqual(APIClient().post("/api/auth/refresh/", {"refresh": "junk"},
                                          format="json").status_code, 401)

    def test_login_is_throttled(self):
        from unittest import mock

        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"login": "3/min"}):
            codes = [self.login("CHW-KWALE-001", "wrong").status_code for _ in range(5)]
        self.assertEqual(codes[:3], [401, 401, 401])
        self.assertEqual(codes[3:], [429, 429])

    def test_superuser_is_admin_role(self):
        su = User.objects.create_superuser("boss", password=PASSWORD)
        self.assertEqual(su.role, "admin")
        self.assertTrue(su.is_salama_admin)
        self.assertEqual(self.client_for(su).get("/api/cases/").status_code, 200)


class ChwManagementTests(BaseTest):
    def test_chw_cannot_manage_chws(self):
        c = self.client_for(self.fatuma)
        self.assertEqual(c.get("/api/chws/").status_code, 403)
        self.assertEqual(c.post("/api/chws/", {}, format="json").status_code, 403)

    def test_admin_creates_chw(self):
        a = self.client_for(self.admin)
        r = a.post("/api/chws/", {
            "username": "chw-kwale-003", "password": "Another-Str0ng-1",
            "full_name": "Mwanaisha", "phone": "0722 000 003", "area": "Lunga Lunga",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.data["username"], "CHW-KWALE-003")  # normalised to upper case
        self.assertEqual(r.data["phone"], "+254722000003")
        self.assertNotIn("password", r.data)
        u = User.objects.get(username="CHW-KWALE-003")
        self.assertEqual(u.role, "chw")
        self.assertFalse(u.is_staff)
        self.assertNotEqual(u.password, "Another-Str0ng-1")  # hashed
        self.assertEqual(self.login("chw-kwale-003", "Another-Str0ng-1").status_code, 200)

    def test_create_validation(self):
        a = self.client_for(self.admin)
        base = {"username": "CHW-KWALE-009", "password": "Another-Str0ng-1"}
        self.assertEqual(a.post("/api/chws/", {**base, "username": "chw-kwale-001"},
                                format="json").status_code, 400)  # duplicate, any case
        self.assertEqual(a.post("/api/chws/", {**base, "password": "123"},
                                format="json").status_code, 400)  # too short / weak
        self.assertEqual(a.post("/api/chws/", {**base, "password": "password"},
                                format="json").status_code, 400)  # common password
        self.assertEqual(a.post("/api/chws/", {"username": "CHW-KWALE-009"},
                                format="json").status_code, 400)  # password required
        self.assertEqual(a.post("/api/chws/", {**base, "phone": "999"},
                                format="json").status_code, 400)

    def test_cannot_create_admin_through_chw_endpoint(self):
        a = self.client_for(self.admin)
        r = a.post("/api/chws/", {"username": "CHW-X-1", "password": "Another-Str0ng-1",
                                  "role": "admin", "is_staff": True, "is_superuser": True},
                   format="json")
        self.assertEqual(r.status_code, 201)
        u = User.objects.get(username="CHW-X-1")
        self.assertEqual((u.role, u.is_staff, u.is_superuser), ("chw", False, False))

    def test_list_shows_workload_and_hides_admins(self):
        make_case("KWALE-2610-AAAAAA", assigned_to=self.fatuma)
        make_case("KWALE-2610-BBBBBB", assigned_to=self.fatuma, status="closed")
        r = self.client_for(self.admin).get("/api/chws/")
        by = {u["username"]: u for u in r.data["results"]}
        self.assertEqual(set(by), {"CHW-KWALE-001", "CHW-KWALE-002"})
        self.assertEqual(by["CHW-KWALE-001"]["open_cases"], 1)

    def test_update_and_password_reset(self):
        a = self.client_for(self.admin)
        r = a.patch(f"/api/chws/{self.ali.pk}/", {"area": "Kinango", "password": "Brand-New-Pass-9"},
                    format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self.login("CHW-KWALE-002", PASSWORD).status_code, 401)
        self.assertEqual(self.login("CHW-KWALE-002", "Brand-New-Pass-9").status_code, 200)

    def test_delete_deactivates_instead_of_deleting(self):
        make_case("KWALE-2610-AAAAAA", assigned_to=self.ali)
        r = self.client_for(self.admin).delete(f"/api/chws/{self.ali.pk}/")
        self.assertEqual(r.status_code, 204)
        self.ali.refresh_from_db()
        self.assertFalse(self.ali.is_active)
        self.assertEqual(self.login("CHW-KWALE-002").status_code, 401)
        # Their cases and audit history are untouched.
        self.assertEqual(self.ali.cases.count(), 1)

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from accounts.models import User
from cases.models import Case, CaseUpdate

from .base import PASSWORD, BaseTest, make_case


class DashboardTests(BaseTest):
    def admin_client(self):
        c = Client()
        c.force_login(self.admin)
        return c

    def test_anonymous_is_sent_to_login(self):
        r = Client().get("/dashboard/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/admin/login/", r["Location"])

    def test_chw_is_forbidden(self):
        c = Client()
        c.force_login(self.fatuma)
        for url in ["/dashboard/", "/dashboard/cases/", "/dashboard/chws/"]:
            self.assertEqual(c.get(url).status_code, 403, url)

    def test_root_redirects_to_dashboard(self):
        self.assertEqual(Client().get("/")["Location"], "/dashboard/")

    def test_index_shows_kpis_without_personal_data(self):
        make_case("SOS-AAAAAA", type="sos", status="sos")
        make_case("KWALE-2610-AAAAAA", description="TOPSECRET-DESC", contact_phone="+254700000000")
        r = self.admin_client().get("/dashboard/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "SOS urgent")
        self.assertContains(r, "SOS-AAAAAA")
        self.assertEqual(r.context["stats"]["total"], 2)
        self.assertEqual(r.context["stats"]["urgent"], 1)
        self.assertNotContains(r, "TOPSECRET-DESC")
        self.assertNotContains(r, "+254700000000")

    def test_index_empty_state(self):
        r = self.admin_client().get("/dashboard/")
        self.assertContains(r, "No cases yet")

    def test_case_list_filters(self):
        make_case("SOS-AAAAAA", type="sos", status="sos")
        make_case("KWALE-2610-AAAAAA", assigned_to=self.fatuma)
        c = self.admin_client()
        self.assertEqual(len(c.get("/dashboard/cases/").context["page"].object_list), 2)
        self.assertEqual(len(c.get("/dashboard/cases/?type=sos").context["page"].object_list), 1)
        self.assertEqual(len(c.get("/dashboard/cases/?assigned=none").context["page"].object_list), 1)
        self.assertEqual(len(c.get("/dashboard/cases/?status=new").context["page"].object_list), 1)
        self.assertEqual(len(c.get("/dashboard/cases/?status=garbage").context["page"].object_list), 2)

    def test_assign_from_dashboard(self):
        case = make_case("KWALE-2610-AAAAAA")
        c = self.admin_client()
        r = c.post(f"/dashboard/cases/{case.pk}/assign/", {"chw": self.ali.pk, "next": "/dashboard/cases/"})
        self.assertEqual(r.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.assigned_to, self.ali)
        self.assertTrue(CaseUpdate.objects.filter(case=case, kind="assign").exists())
        c.post(f"/dashboard/cases/{case.pk}/assign/", {"chw": ""})
        case.refresh_from_db()
        self.assertIsNone(case.assigned_to)

    def test_assign_rejects_non_chw_and_get(self):
        case = make_case("KWALE-2610-AAAAAA")
        c = self.admin_client()
        self.assertEqual(c.post(f"/dashboard/cases/{case.pk}/assign/",
                                {"chw": self.admin.pk}).status_code, 404)
        self.assertEqual(c.get(f"/dashboard/cases/{case.pk}/assign/").status_code, 405)

    def test_chw_cannot_assign(self):
        case = make_case("KWALE-2610-AAAAAA")
        c = Client()
        c.force_login(self.fatuma)
        self.assertEqual(c.post(f"/dashboard/cases/{case.pk}/assign/", {"chw": self.fatuma.pk}).status_code, 403)

    def test_chw_page(self):
        r = self.admin_client().get("/dashboard/chws/")
        self.assertContains(r, "CHW-KWALE-001")

    def test_django_admin_pages_open_for_admin(self):
        case = make_case("KWALE-2610-AAAAAA")
        su = User.objects.create_superuser("root", password=PASSWORD)
        c = Client()
        c.force_login(su)
        self.assertEqual(c.get("/admin/cases/case/").status_code, 200)
        self.assertEqual(c.get(f"/admin/cases/case/{case.pk}/change/").status_code, 200)
        self.assertEqual(c.get("/admin/cases/smsinbound/").status_code, 200)
        self.assertEqual(c.get("/admin/accounts/user/").status_code, 200)
        self.assertEqual(c.get("/admin/accounts/user/add/").status_code, 200)

    def test_admin_action_mark_closed(self):
        case = make_case("KWALE-2610-AAAAAA")
        su = User.objects.create_superuser("root", password=PASSWORD)
        c = Client()
        c.force_login(su)
        r = c.post("/admin/cases/case/", {"action": "mark_closed", "_selected_action": [str(case.pk)]})
        self.assertEqual(r.status_code, 302)
        case.refresh_from_db()
        self.assertEqual(case.status, "closed")
        self.assertTrue(case.updates.filter(kind="status", to_status="closed").exists())


class CommandTests(BaseTest):
    def test_seed_demo(self):
        out = StringIO()
        User.objects.filter(username="CHW-KWALE-001").delete()
        call_command("seed_demo", "--password", "Another-Str0ng-1", stdout=out)
        self.assertTrue(User.objects.filter(username="CHW-KWALE-001", role="chw").exists())
        self.assertTrue(User.objects.filter(username="CHW-KWALE-004").exists())
        call_command("seed_demo", stdout=StringIO())  # idempotent

    def test_purge_old_cases(self):
        old_closed = make_case("KWALE-2610-AAAAAA", status="closed")
        old_open = make_case("KWALE-2610-BBBBBB", status="responded")
        fresh_closed = make_case("KWALE-2610-CCCCCC", status="closed")
        long_ago = timezone.now() - timedelta(days=400)
        Case.objects.filter(pk__in=[old_closed.pk, old_open.pk]).update(updated_at=long_ago)
        call_command("purge_old_cases", "--dry-run", stdout=StringIO())
        self.assertEqual(Case.objects.count(), 3)
        call_command("purge_old_cases", "--days", "365", stdout=StringIO())
        self.assertEqual(set(Case.objects.values_list("case_ref", flat=True)),
                         {"KWALE-2610-BBBBBB", "KWALE-2610-CCCCCC"})  # only OLD + CLOSED removed

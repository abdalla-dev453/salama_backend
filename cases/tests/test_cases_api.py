from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from cases.models import Case, CaseUpdate

from .base import BaseTest, make_case


class CaseVisibilityTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.mine = make_case("KWALE-2610-AAAAAA", assigned_to=self.fatuma)
        self.theirs = make_case("KWALE-2610-BBBBBB", assigned_to=self.ali)
        self.open_one = make_case("KWALE-2610-CCCCCC")

    def refs(self, resp):
        return [c["case_ref"] for c in resp.data["results"]]

    def test_requires_login(self):
        self.assertEqual(APIClient().get("/api/cases/").status_code, 401)
        self.assertEqual(APIClient().get("/api/stats/").status_code, 401)

    def test_chw_sees_own_and_unassigned_only(self):
        r = self.client_for(self.fatuma).get("/api/cases/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(self.refs(r)), {"KWALE-2610-AAAAAA", "KWALE-2610-CCCCCC"})

    def test_admin_sees_everything(self):
        r = self.client_for(self.admin).get("/api/cases/")
        self.assertEqual(len(self.refs(r)), 3)

    def test_other_chws_case_is_404(self):
        c = self.client_for(self.fatuma)
        self.assertEqual(c.get(f"/api/cases/{self.theirs.pk}/").status_code, 404)
        self.assertEqual(c.post(f"/api/cases/{self.theirs.pk}/status/",
                                {"status": "closed"}, format="json").status_code, 404)
        self.assertEqual(c.post(f"/api/cases/{self.theirs.pk}/claim/").status_code, 404)

    def test_unanswered_sos_comes_first(self):
        old_sos = make_case("SOS-AAAAAA", type="sos", status="sos")
        Case.objects.filter(pk=old_sos.pk).update(received_at=timezone.now() - timedelta(days=3))
        r = self.client_for(self.admin).get("/api/cases/")
        self.assertEqual(self.refs(r)[0], "SOS-AAAAAA")
        self.assertTrue(r.data["results"][0]["is_urgent"])
        self.assertEqual(r.data["results"][0]["priority"], "urgent")

    def test_filters(self):
        make_case("SOS-BBBBBB", type="sos", status="sos")
        c = self.client_for(self.fatuma)
        self.assertEqual(self.refs(c.get("/api/cases/?scope=mine")), ["KWALE-2610-AAAAAA"])
        self.assertEqual(set(self.refs(c.get("/api/cases/?scope=unassigned"))),
                         {"KWALE-2610-CCCCCC", "SOS-BBBBBB"})
        self.assertEqual(self.refs(c.get("/api/cases/?scope=urgent")), ["SOS-BBBBBB"])
        self.assertEqual(self.refs(c.get("/api/cases/?type=sos")), ["SOS-BBBBBB"])
        self.assertEqual(len(self.refs(c.get("/api/cases/?status=new"))), 2)
        self.assertEqual(self.refs(c.get("/api/cases/?search=BBBBBB")), ["SOS-BBBBBB"])

    def test_pagination_shape(self):
        r = self.client_for(self.admin).get("/api/cases/?page_size=2")
        self.assertEqual(set(r.data), {"count", "next", "previous", "results"})
        self.assertEqual(len(r.data["results"]), 2)
        self.assertEqual(r.data["count"], 3)

    def test_detail_has_audit_trail_and_details(self):
        r = self.client_for(self.fatuma).get(f"/api/cases/{self.mine.pk}/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["description"], "secret description")
        self.assertEqual(r.data["assigned_to_name"], "Fatuma")
        self.assertIn("updates", r.data)

    def test_read_only(self):
        c = self.client_for(self.admin)
        self.assertEqual(c.delete(f"/api/cases/{self.mine.pk}/").status_code, 405)
        self.assertEqual(c.patch(f"/api/cases/{self.mine.pk}/", {"status": "closed"},
                                 format="json").status_code, 405)
        self.assertEqual(c.post("/api/cases/", {}, format="json").status_code, 405)


class WorkflowTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.case = make_case("KWALE-2610-AAAAAA")
        self.sos = make_case("SOS-AAAAAA", type="sos", status="sos")

    def test_claim_then_conflict(self):
        r = self.client_for(self.fatuma).post(f"/api/cases/{self.case.pk}/claim/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["assigned_to"], self.fatuma.pk)
        self.assertEqual(r.data["updates"][-1]["kind"], "assign")
        # Same CHW again: fine. Another CHW: the case is not visible to them (404).
        self.assertEqual(self.client_for(self.fatuma).post(f"/api/cases/{self.case.pk}/claim/").status_code, 200)
        self.assertEqual(self.client_for(self.ali).post(f"/api/cases/{self.case.pk}/claim/").status_code, 404)

    def test_simultaneous_claim_conflict_is_409(self):
        # Ali loaded the case while it was free; Fatuma claims first; Ali's claim must not win.
        from cases.services import workflow

        workflow.claim_case(self.case, self.fatuma)
        from cases.services.workflow import Conflict

        with self.assertRaises(Conflict):
            workflow.claim_case(self.case, self.ali)
        self.case.refresh_from_db()
        self.assertEqual(self.case.assigned_to, self.fatuma)

    def test_chw_changes_status_and_it_is_logged(self):
        c = self.client_for(self.fatuma)
        r = c.post(f"/api/cases/{self.case.pk}/status/",
                   {"status": "responded", "note": "Visited the family"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["status"], "responded")
        self.assertEqual(r.data["assigned_to"], self.fatuma.pk)  # auto-claimed
        last = r.data["updates"][-1]
        self.assertEqual((last["kind"], last["from_status"], last["to_status"], last["note"]),
                         ("status", "new", "responded", "Visited the family"))
        self.assertEqual(last["author_name"], "Fatuma")

    def test_sos_stops_being_urgent_once_responded(self):
        c = self.client_for(self.fatuma)
        self.assertEqual(c.get("/api/stats/").data["urgent"], 1)
        c.post(f"/api/cases/{self.sos.pk}/status/", {"status": "responded"}, format="json")
        self.assertEqual(c.get("/api/stats/").data["urgent"], 0)

    def test_invalid_status(self):
        r = self.client_for(self.fatuma).post(f"/api/cases/{self.case.pk}/status/",
                                              {"status": "bogus"}, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client_for(self.fatuma).post(f"/api/cases/{self.case.pk}/status/", {}, format="json")
        self.assertEqual(r.status_code, 400)

    def test_admin_can_change_any_status(self):
        self.case.assigned_to = self.ali
        self.case.save()
        r = self.client_for(self.admin).post(f"/api/cases/{self.case.pk}/status/",
                                             {"status": "closed"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, "closed")
        self.assertEqual(self.case.assigned_to, self.ali)  # admin does not steal ownership

    def test_note(self):
        c = self.client_for(self.fatuma)
        r = c.post(f"/api/cases/{self.case.pk}/note/", {"note": "Called the clinic"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["updates"][-1]["kind"], "note")
        self.assertEqual(r.data["updates"][-1]["note"], "Called the clinic")
        self.assertEqual(c.post(f"/api/cases/{self.case.pk}/note/", {"note": ""},
                                format="json").status_code, 400)

    def test_admin_assign_and_unassign(self):
        a = self.client_for(self.admin)
        r = a.post(f"/api/cases/{self.case.pk}/assign/", {"chw": self.ali.pk}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data["assigned_to_name"], "Ali")
        self.assertEqual(CaseUpdate.objects.filter(case=self.case, kind="assign").count(), 1)
        r = a.post(f"/api/cases/{self.case.pk}/assign/", {"chw": None}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.data["assigned_to"])

    def test_assign_rules(self):
        a = self.client_for(self.admin)
        self.assertEqual(a.post(f"/api/cases/{self.case.pk}/assign/",
                                {"chw": self.admin.pk}, format="json").status_code, 400)
        self.ali.is_active = False
        self.ali.save()
        self.assertEqual(a.post(f"/api/cases/{self.case.pk}/assign/",
                                {"chw": self.ali.pk}, format="json").status_code, 400)
        # A CHW can never assign.
        self.assertEqual(self.client_for(self.fatuma).post(
            f"/api/cases/{self.case.pk}/assign/", {"chw": self.fatuma.pk}, format="json").status_code, 403)


class StatsTests(BaseTest):
    def setUp(self):
        super().setUp()
        make_case("KWALE-2610-AAAAAA", status="new")
        make_case("KWALE-2610-BBBBBB", status="responded", assigned_to=self.fatuma)
        make_case("KWALE-2610-CCCCCC", status="referred", assigned_to=self.ali)
        make_case("KWALE-2610-DDDDDD", status="closed", assigned_to=self.ali)
        make_case("SOS-AAAAAA", type="sos", status="sos")
        make_case("SOS-BBBBBB", type="sos", status="followup", assigned_to=self.ali)

    def test_admin_stats(self):
        d = self.client_for(self.admin).get("/api/stats/").data
        self.assertEqual(d["total"], 6)
        self.assertEqual(d["pending"], 2)   # new + sos
        self.assertEqual(d["active"], 2)    # responded + referred
        self.assertEqual(d["urgent"], 1)
        self.assertEqual(d["referred"], 1)
        self.assertEqual(d["closed"], 1)
        self.assertEqual(d["by_type"]["sos"], 2)
        self.assertEqual(d["by_status"]["followup"], 1)
        self.assertEqual(len(d["trend"]), 30)
        self.assertEqual(sum(x["count"] for x in d["trend"]), 6)
        self.assertEqual(d["trend"][-1]["count"], 6)  # all created today
        self.assertEqual(d["last_7_days"], 6)

    def test_chw_stats_cover_only_visible_cases(self):
        d = self.client_for(self.fatuma).get("/api/stats/").data
        # Fatuma: her own (responded) + unassigned (new, SOS) = 3
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["urgent"], 1)
        self.assertEqual(d["active"], 1)

    def test_empty(self):
        Case.objects.all().delete()
        d = self.client_for(self.admin).get("/api/stats/").data
        self.assertEqual((d["total"], d["urgent"]), (0, 0))
        self.assertEqual(d["by_status"], {})


class HealthTests(BaseTest):
    def test_health(self):
        r = APIClient().get("/api/health/")
        self.assertEqual((r.status_code, r.data), (200, {"status": "ok"}))

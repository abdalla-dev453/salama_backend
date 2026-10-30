from datetime import timedelta

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cases.models import Case, CaseStatus, CaseType, CaseUpdate
from cases.tests.base import BaseTest, make_case
from extras.models import DeviceToken, HelpContact
from extras.ussd import handle


class HelpDirectoryTests(BaseTest):
    def test_public_list_only_active(self):
        HelpContact.objects.create(name="Kwale Hospital", category="clinic", phone="0711000000")
        HelpContact.objects.create(name="Old", category="clinic", is_active=False)
        r = APIClient().get("/api/help-directory/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["name"] for c in r.data["contacts"]], ["Kwale Hospital"])
        self.assertIsNotNone(r.data["version"])


class StatusCheckTests(BaseTest):
    def test_status_only_no_personal_data(self):
        make_case("KWALE-2610-AAAAAA", status=CaseStatus.REFERRED, assigned_to=self.fatuma)
        r = APIClient().get("/api/status/kwale-2610-aaaaaa/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["status"], "referred")
        self.assertEqual(set(r.data), {"found", "case_ref", "status", "updated_at"})

    def test_unknown_and_bad_format_look_the_same(self):
        a = APIClient().get("/api/status/KWALE-2610-ZZZZZZ/")
        b = APIClient().get("/api/status/not-a-ref/")
        self.assertEqual((a.status_code, a.data), (404, {"found": False}))
        self.assertEqual((b.status_code, b.data), (404, {"found": False}))

    def test_throttled(self):
        c = APIClient()
        codes = [c.get("/api/status/KWALE-2610-ZZZZZZ/").status_code for _ in range(35)]
        self.assertIn(429, codes)


class DeviceTokenTests(BaseTest):
    def test_register_and_remove(self):
        c = self.client_for(self.fatuma)
        tok = "x" * 40
        self.assertEqual(c.post("/api/devices/", {"token": tok}, format="json").status_code, 200)
        self.assertEqual(DeviceToken.objects.filter(user=self.fatuma).count(), 1)
        self.assertEqual(c.delete("/api/devices/", {"token": tok}, format="json").status_code, 204)
        self.assertEqual(DeviceToken.objects.count(), 0)

    def test_anonymous_cannot_register(self):
        r = APIClient().post("/api/devices/", {"token": "x" * 40}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_push_does_nothing_without_firebase(self):
        from extras.push import push_sos_to_chws

        self.assertEqual(push_sos_to_chws("SOS-AAAAAA"), 0)


class ReportTests(BaseTest):
    def setUp(self):
        super().setUp()
        for i in range(6):
            make_case(f"KWALE-2610-A0000{i}", location_text="Ukunda beach road")
        make_case("KWALE-2610-B00001", location_text="Kinango")

    def test_admin_only(self):
        self.assertEqual(self.client_for(self.fatuma).get("/api/reports/anonymous/").status_code, 403)
        self.assertEqual(APIClient().get("/api/reports/anonymous/").status_code, 401)

    def test_small_cells_hidden_and_no_personal_data(self):
        r = self.client_for(self.admin).get("/api/reports/anonymous/")
        rows = {(x["area"], x["type"]): x["count"] for x in r.data["rows"]}
        self.assertEqual(rows[("Ukunda", "violence")], 6)
        self.assertEqual(rows[("Kinango", "violence")], "<5")
        self.assertNotIn("secret", str(r.data))

    def test_csv(self):
        r = self.client_for(self.admin).get("/api/reports/anonymous.csv")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertTrue(body.startswith("month,area,type,count"))
        self.assertIn("Ukunda", body)
        self.assertNotIn("secret", body)

    def test_response_times(self):
        sos = make_case("SOS-AAAAAA", type=CaseType.SOS, status=CaseStatus.SOS)
        CaseUpdate.objects.create(case=sos, author=self.fatuma, kind=CaseUpdate.Kind.NOTE, note="on it")
        r = self.client_for(self.admin).get("/api/reports/response-times/")
        self.assertEqual(r.data["sos"]["cases"], 1)
        self.assertEqual(r.data["per_chw"]["CHW-KWALE-001"]["cases"], 1)
        self.assertEqual(r.data["never_answered"], 7)


@override_settings(AT_WEBHOOK_TOKEN="tok")
class UssdTests(BaseTest):
    def test_flow_sos_is_idempotent(self):
        out1 = handle("sess1", "+254712345678", "2*1*1")
        out2 = handle("sess1", "+254712345678", "2*1*1")  # AT retry
        self.assertEqual(out1, out2)
        self.assertTrue(out1.startswith("END"))
        c = Case.objects.get(type=CaseType.SOS)
        self.assertTrue(c.safe_to_call)
        self.assertEqual(c.contact_phone, "+254712345678")
        self.assertEqual(Case.objects.count(), 1)

    def test_report_flow(self):
        self.assertIn("Aina", handle("s2", "0712345678", "1*2"))
        self.assertIn("Uko wapi", handle("s2", "0712345678", "1*2*1"))
        out = handle("s2", "0712345678", "1*2*1*Ukunda*2")
        self.assertIn("Kumbukumbu", out)
        c = Case.objects.get()
        self.assertEqual((c.type, c.location_text, c.safe_to_call), ("violence", "Ukunda", False))

    def test_status_and_help(self):
        make_case("KWALE-2610-AAAAAA", status=CaseStatus.CLOSED)
        self.assertIn("Closed", handle("s3", "0712345678", "2*3*KWALE-2610-AAAAAA"))
        self.assertIn("1195", handle("s3", "0712345678", "2*4"))

    def test_webhook_needs_token_and_returns_plain_text(self):
        c = APIClient()
        body = {"sessionId": "s9", "phoneNumber": "+254712345678", "text": ""}
        self.assertEqual(c.post("/api/ussd/africastalking/", body).status_code, 403)
        r = c.post("/api/ussd/africastalking/?token=tok", body)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.decode().startswith("CON"))

    @override_settings(AT_WEBHOOK_TOKEN="")
    def test_disabled_without_token(self):
        r = APIClient().post("/api/ussd/africastalking/?token=", {"sessionId": "s"})
        self.assertEqual(r.status_code, 403)


class CaseworkTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.case = make_case("KWALE-2610-CCCCCC", assigned_to=self.fatuma)

    def _url(self, what):
        return f"/api/cases/{self.case.id}/{what}/"

    def test_followup_lifecycle(self):
        c = self.client_for(self.fatuma)
        due = (timezone.localdate() + timedelta(days=3)).isoformat()
        r = c.post(self._url("followups"), {"due_date": due, "note": "visit"}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        mine = c.get("/api/followups/mine/")
        self.assertEqual(len(mine.data), 1)
        self.assertEqual(c.patch(f"/api/followups/{r.data['id']}/", {"done": True}, format="json").data["done"], True)
        self.assertEqual(len(c.get("/api/followups/mine/").data), 0)

    def test_past_date_rejected(self):
        c = self.client_for(self.fatuma)
        past = (timezone.localdate() - timedelta(days=1)).isoformat()
        self.assertEqual(c.post(self._url("followups"), {"due_date": past}, format="json").status_code, 400)

    def test_other_chw_cannot_write(self):
        c = self.client_for(self.ali)
        r = c.get(self._url("followups"))
        self.assertEqual(r.status_code, 404)  # not visible: assigned to someone else

    def test_unassigned_case_is_read_only_until_claimed(self):
        free = make_case("KWALE-2610-DDDDDD")
        c = self.client_for(self.ali)
        due = (timezone.localdate() + timedelta(days=1)).isoformat()
        r = c.post(f"/api/cases/{free.id}/followups/", {"due_date": due}, format="json")
        self.assertEqual(r.status_code, 403)

    def test_referral(self):
        hc = HelpContact.objects.create(name="Kwale Hospital", category="clinic")
        c = self.client_for(self.fatuma)
        r = c.post(self._url("referrals"), {"contact": hc.id}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data["contact_name"], "Kwale Hospital")
        r2 = c.patch(f"/api/referrals/{r.data['id']}/", {"outcome": "attended"}, format="json")
        self.assertEqual(r2.data["outcome"], "attended")
        self.assertEqual(c.post(self._url("referrals"), {}, format="json").status_code, 400)

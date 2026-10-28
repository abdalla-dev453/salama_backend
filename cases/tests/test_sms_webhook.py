from urllib.parse import urlencode

from django.test import override_settings
from rest_framework.test import APIClient

from cases.models import Case, SmsInbound

from .base import BaseTest

URL = "/api/sms/africastalking/"
FORM = "application/x-www-form-urlencoded"


def post(token="s3cret", **fields):
    """Posts exactly like Africa's Talking: a form-encoded body."""
    body = {"from": "+254712345678", "to": "20414", "text": "", "id": "ATXid_1",
            "date": "2026-10-27 10:00:00", "linkId": "x"}
    body.update(fields)
    url = URL + (f"?token={token}" if token is not None else "")
    return APIClient().post(url, urlencode(body), content_type=FORM)


@override_settings(AT_WEBHOOK_TOKEN="s3cret")
class SmsWebhookTests(BaseTest):
    def test_report_creates_case_with_sender_as_contact(self):
        r = post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|-4.28000,39.57000")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.data, {"ok": True, "parsed": True, "case_ref": "KWALE-2610-AB12CD"})
        c = Case.objects.get()
        self.assertEqual(c.source, "sms")
        self.assertEqual(c.type, "violence")
        self.assertEqual(c.contact_phone, "+254712345678")  # sender
        self.assertFalse(c.safe_to_call)                     # unknown -> never "safe to call"
        self.assertAlmostEqual(c.lat, -4.28)
        sms = SmsInbound.objects.get()
        self.assertTrue(sms.parsed)
        self.assertEqual(sms.case, c)
        self.assertEqual(sms.sender, "+254712345678")

    def test_contact_in_message_wins_over_sender(self):
        post(text="SALAMA:KWALE-2610-AB12CD|C|Kinango|NA,NA|0722000111|1")
        c = Case.objects.get()
        self.assertEqual(c.contact_phone, "+254722000111")
        self.assertTrue(c.safe_to_call)

    def test_sos_sms(self):
        post(text="SOS! SOS-ABC123 Lunga Lunga https://maps.google.com/?q=-4.5,39.1")
        c = Case.objects.get()
        self.assertEqual((c.type, c.status, c.source), ("sos", "sos", "sms"))
        self.assertAlmostEqual(c.lon, 39.1)

    def test_duplicate_delivery_is_ignored(self):
        post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA", id="ATXid_9")
        r = post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA", id="ATXid_9")
        self.assertTrue(r.data["duplicate"])
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(SmsInbound.objects.count(), 1)

    def test_same_case_sent_twice_with_new_message_id_does_not_duplicate(self):
        post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA", id="a")
        post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA", id="b")
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(SmsInbound.objects.count(), 2)

    def test_unparseable_message_is_kept_for_a_human(self):
        r = post(text="Hello I need help", id="z1")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["parsed"])
        self.assertEqual(Case.objects.count(), 0)
        sms = SmsInbound.objects.get()
        self.assertFalse(sms.parsed)
        self.assertEqual(sms.text, "Hello I need help")

    def test_token_required(self):
        for token in [None, "", "wrong"]:
            r = post(token=token, text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA")
            self.assertEqual(r.status_code, 403, token)
        self.assertEqual(Case.objects.count(), 0)

    def test_token_via_header(self):
        r = APIClient().post(URL, urlencode({"from": "+254712345678", "id": "h1",
                             "text": "SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA"}),
                             content_type=FORM, HTTP_X_WEBHOOK_TOKEN="s3cret")
        self.assertEqual(r.status_code, 200)

    def test_sender_that_is_not_a_kenyan_mobile_is_kept_out_of_the_case(self):
        post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA", **{"from": "MPESA"})
        self.assertEqual(Case.objects.get().contact_phone, "")

    def test_get_not_allowed(self):
        self.assertEqual(APIClient().get(URL + "?token=s3cret").status_code, 405)

    def test_sms_then_app_sync_enriches_the_same_case(self):
        post(text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA")
        r = APIClient().post("/api/intake/", {
            "case_ref": "KWALE-2610-AB12CD", "type": "violence",
            "description": "Details only the app has", "lat": -4.3, "lon": 39.6,
        }, format="json")
        self.assertEqual(r.status_code, 200)
        c = Case.objects.get()
        self.assertEqual(c.description, "Details only the app has")
        self.assertAlmostEqual(c.lat, -4.3)
        self.assertEqual(c.source, "sms")  # first channel is kept


class SmsWebhookDisabledTests(BaseTest):
    @override_settings(AT_WEBHOOK_TOKEN="")
    def test_fails_closed_when_no_token_configured(self):
        r = post(token="", text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA")
        self.assertEqual(r.status_code, 403)
        r = post(token=None, text="SALAMA:KWALE-2610-AB12CD|V|Ukunda|NA,NA")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(Case.objects.count(), 0)

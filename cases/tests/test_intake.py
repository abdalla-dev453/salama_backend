from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from cases.models import Case, CaseUpdate

from .base import BaseTest

URL = "/api/intake/"


def payload(**kw):
    d = {
        "case_ref": "KWALE-2610-AB12CD",
        "type": "violence",
        "description": "Short confidential description",
        "location_text": "Ukunda",
        "lat": -4.28,
        "lon": 39.57,
        "contact_phone": "0712 345 678",
        "safe_to_call": True,
    }
    d.update(kw)
    return d


class IntakeTests(BaseTest):
    def setUp(self):
        super().setUp()
        self.anon = APIClient()

    def test_creates_case_without_login(self):
        r = self.anon.post(URL, payload(), format="json")
        self.assertEqual(r.status_code, 201, r.content)
        # Anonymous callers get a receipt only, never case data.
        self.assertEqual(set(r.data), {"case_ref", "status", "created"})
        c = Case.objects.get(case_ref="KWALE-2610-AB12CD")
        self.assertEqual(c.status, "new")
        self.assertEqual(c.source, "app")
        self.assertEqual(c.contact_phone, "+254712345678")
        self.assertTrue(c.safe_to_call)
        self.assertEqual(c.updates.filter(kind=CaseUpdate.Kind.CREATED).count(), 1)

    def test_idempotent(self):
        self.anon.post(URL, payload(), format="json")
        r = self.anon.post(URL, payload(), format="json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data["created"])
        self.assertEqual(Case.objects.count(), 1)
        self.assertEqual(CaseUpdate.objects.count(), 1)

    def test_resend_never_overwrites_existing_data(self):
        self.anon.post(URL, payload(), format="json")
        self.anon.post(URL, payload(description="CHANGED", location_text="Elsewhere",
                                    lat=1.0, lon=2.0), format="json")
        c = Case.objects.get()
        self.assertEqual(c.description, "Short confidential description")
        self.assertEqual(c.location_text, "Ukunda")
        self.assertAlmostEqual(c.lat, -4.28)

    def test_resend_fills_missing_gps_and_description(self):
        # SOS first without GPS, then the app finds GPS and re-sends.
        self.anon.post(URL, {"case_ref": "SOS-ABC123", "type": "sos"}, format="json")
        c = Case.objects.get()
        self.assertIsNone(c.lat)
        self.assertEqual(c.status, "sos")
        self.anon.post(URL, {"case_ref": "SOS-ABC123", "type": "sos", "lat": -4.1, "lon": 39.2,
                             "location_text": "Msambweni"}, format="json")
        c.refresh_from_db()
        self.assertAlmostEqual(c.lat, -4.1)
        self.assertEqual(c.location_text, "Msambweni")

    def test_sos_needs_no_description(self):
        r = self.anon.post(URL, {"case_ref": "SOS-ABC123", "type": "sos"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)

    def test_description_required_for_reports(self):
        r = self.anon.post(URL, payload(description=""), format="json")
        self.assertEqual(r.status_code, 400)

    def test_validation(self):
        bad = [
            payload(case_ref="HACK"),
            payload(case_ref="KWALE-2610-ab12cd"),
            payload(type="nonsense"),
            payload(contact_phone="123"),
            payload(lat=95),
            payload(lon=181),
            payload(lon=None),            # lat without lon
            payload(description="x" * 4001),
            payload(location_text="x" * 201),
        ]
        for p in bad:
            r = self.anon.post(URL, p, format="json")
            self.assertEqual(r.status_code, 400, p)
        self.assertEqual(Case.objects.count(), 0)

    def test_optional_fields(self):
        r = self.anon.post(URL, {"case_ref": "KWALE-2610-AB12CD", "type": "counseling",
                                 "description": "help"}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        c = Case.objects.get()
        self.assertIsNone(c.lat)
        self.assertEqual(c.contact_phone, "")
        self.assertFalse(c.safe_to_call)

    def test_reported_at_is_clamped(self):
        future = (timezone.now() + timedelta(days=30)).isoformat()
        self.anon.post(URL, payload(reported_at=future), format="json")
        self.assertLessEqual(Case.objects.get().reported_at, timezone.now())
        Case.objects.all().delete()
        old = (timezone.now() - timedelta(days=900)).isoformat()
        self.anon.post(URL, payload(reported_at=old), format="json")
        self.assertGreater(Case.objects.get().reported_at, timezone.now() - timedelta(days=2))

    def test_reported_at_kept_when_sensible(self):
        when = timezone.now() - timedelta(hours=5)
        self.anon.post(URL, payload(reported_at=when.isoformat()), format="json")
        self.assertAlmostEqual(Case.objects.get().reported_at.timestamp(), when.timestamp(), delta=1)

    @override_settings(SURVIVOR_API_KEY="app-key-123")
    def test_api_key(self):
        self.assertEqual(self.anon.post(URL, payload(), format="json").status_code, 401)
        r = self.anon.post(URL, payload(), format="json", HTTP_X_SALAMA_KEY="wrong")
        self.assertEqual(r.status_code, 401)
        r = self.anon.post(URL, payload(), format="json", HTTP_X_SALAMA_KEY="app-key-123")
        self.assertEqual(r.status_code, 201)

    def test_bad_token_header_does_not_break_anonymous_intake(self):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION="Bearer not-a-real-token")
        self.assertEqual(c.post(URL, payload(), format="json").status_code, 201)

    def test_throttled(self):
        from rest_framework.throttling import SimpleRateThrottle

        with mock.patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"intake": "3/min"}):
            codes = [
                self.anon.post(URL, payload(case_ref=f"KWALE-2610-AAAA0{i}"), format="json").status_code
                for i in range(5)
            ]
        self.assertEqual(codes[:3], [201, 201, 201])
        self.assertEqual(codes[3:], [429, 429])

    def test_get_not_allowed(self):
        self.assertEqual(self.anon.get(URL).status_code, 405)

    def test_sensitive_fields_encrypted_in_database(self):
        self.anon.post(URL, payload(), format="json")
        with connection.cursor() as cur:
            cur.execute("SELECT description, contact_phone FROM cases_case")
            raw_desc, raw_phone = cur.fetchone()
        self.assertNotIn("confidential", raw_desc)
        self.assertNotIn("712345678", raw_phone)
        c = Case.objects.get()  # but the ORM decrypts transparently
        self.assertEqual(c.description, "Short confidential description")
        self.assertEqual(c.contact_phone, "+254712345678")


class SosAlertTests(BaseTest):
    @override_settings(NOTIFY_CHWS_ON_SOS=True, AT_USERNAME="sandbox", AT_API_KEY="k", AT_SANDBOX=True)
    def test_chws_are_sms_alerted_without_personal_data(self):
        with mock.patch("cases.services.notify.requests.post") as post:
            with self.captureOnCommitCallbacks(execute=True):
                APIClient().post(URL, {"case_ref": "SOS-ABC123", "type": "sos", "lat": -4.2,
                                       "lon": 39.5, "location_text": "Ukunda"}, format="json")
        self.assertEqual(post.call_count, 1)
        sent = post.call_args.kwargs["data"]
        self.assertEqual(set(sent["to"].split(",")), {"+254712000001", "+254712000002"})
        self.assertIn("SOS-ABC123", sent["message"])
        self.assertNotIn("Ukunda", sent["message"])
        self.assertNotIn("-4.2", sent["message"])
        self.assertIn("sandbox", post.call_args.args[0])

    @override_settings(NOTIFY_CHWS_ON_SOS=True, AT_USERNAME="u", AT_API_KEY="k")
    def test_alert_failure_never_breaks_intake(self):
        with mock.patch("cases.services.notify.requests.post", side_effect=RuntimeError("boom")):
            with self.captureOnCommitCallbacks(execute=True):
                r = APIClient().post(URL, {"case_ref": "SOS-ABC123", "type": "sos"}, format="json")
        self.assertEqual(r.status_code, 201)

    def test_no_alert_when_disabled_or_not_sos(self):
        with mock.patch("cases.services.notify.requests.post") as post:
            with self.captureOnCommitCallbacks(execute=True):
                APIClient().post(URL, {"case_ref": "SOS-ABC123", "type": "sos"}, format="json")
                APIClient().post(URL, payload(), format="json")
        post.assert_not_called()

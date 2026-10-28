from django.test import SimpleTestCase

from cases.parsing import parse_sms
from cases.phones import normalize_ke_phone


class PhoneTests(SimpleTestCase):
    def test_formats(self):
        for raw in ["0712345678", "0712 345 678", "+254712345678", "254712345678", "0112345678"]:
            self.assertTrue(normalize_ke_phone(raw).startswith("+254"), raw)
        self.assertEqual(normalize_ke_phone("0712345678"), "+254712345678")
        self.assertEqual(normalize_ke_phone(""), "")

    def test_rejects(self):
        for raw in ["12345", "0912345678", "+255712345678", "abc", "07123456789"]:
            with self.assertRaises(ValueError, msg=raw):
                normalize_ke_phone(raw)


class ParseSmsTests(SimpleTestCase):
    """Strings are exactly what lib/services/sms_service.dart produces."""

    def test_report_full(self):
        d = parse_sms("SALAMA:KWALE-2610-AB12CD|V|Ukunda, Diani|-4.28000,39.57000|0712345678|1")
        self.assertEqual(d["case_ref"], "KWALE-2610-AB12CD")
        self.assertEqual(d["type"], "violence")
        self.assertEqual(d["location_text"], "Ukunda, Diani")
        self.assertAlmostEqual(d["lat"], -4.28)
        self.assertAlmostEqual(d["lon"], 39.57)
        self.assertEqual(d["contact_phone"], "+254712345678")
        self.assertTrue(d["safe_to_call"])

    def test_report_no_gps_no_contact(self):
        d = parse_sms("SALAMA:KWALE-2610-AB12CD|A|Msambweni|NA,NA")
        self.assertEqual(d["type"], "care")
        self.assertIsNone(d["lat"])
        self.assertIsNone(d["lon"])
        self.assertEqual(d["contact_phone"], "")
        self.assertFalse(d["safe_to_call"])

    def test_codes(self):
        for code, t in [("V", "violence"), ("A", "care"), ("C", "counseling"), ("SOS", "sos")]:
            ref = "SOS-ABC123" if code == "SOS" else "KWALE-2610-ABC123"
            self.assertEqual(parse_sms(f"SALAMA:{ref}|{code}|x|NA,NA")["type"], t)

    def test_not_safe(self):
        d = parse_sms("SALAMA:KWALE-2610-AB12CD|C|Kinango|NA,NA|0712345678|0")
        self.assertFalse(d["safe_to_call"])

    def test_sos_with_map_link(self):
        d = parse_sms("SOS! SOS-ABC123 Lunga Lunga https://maps.google.com/?q=-4.5,39.1")
        self.assertEqual(d["type"], "sos")
        self.assertEqual(d["case_ref"], "SOS-ABC123")
        self.assertEqual(d["location_text"], "Lunga Lunga")
        self.assertAlmostEqual(d["lat"], -4.5)
        self.assertAlmostEqual(d["lon"], 39.1)

    def test_sos_without_gps(self):
        d = parse_sms("SOS! SOS-ABC123 Kwale")
        self.assertEqual(d["location_text"], "Kwale")
        self.assertIsNone(d["lat"])

    def test_garbage(self):
        for t in ["", "hello", "SALAMA:BAD|V|x|NA,NA", "SALAMA:KWALE-2610-AB12CD|Z|x|NA,NA",
                  "SOS! not-a-ref somewhere", None]:
            self.assertIsNone(parse_sms(t), t)

    def test_bad_coordinates_ignored(self):
        d = parse_sms("SALAMA:KWALE-2610-AB12CD|V|x|999.0,999.0")
        self.assertIsNone(d["lat"])

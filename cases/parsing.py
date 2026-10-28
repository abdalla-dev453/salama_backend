"""
Parses the SMS formats produced by the Flutter app (lib/services/sms_service.dart):

  Report:  SALAMA:<ref>|<V|A|C|SOS>|<location>|<lat>,<lon>[|<contact>|<safe 1/0>]
  SOS:     SOS! <ref> <location> [https://maps.google.com/?q=<lat>,<lon>]

'NA,NA' means no coordinates. The free-text description is never sent by SMS.
"""
import re

from .models import CASE_REF_REGEX, CaseType
from .phones import normalize_ke_phone

_REF_RE = re.compile(CASE_REF_REGEX)

_REPORT_RE = re.compile(
    r"^\s*SALAMA:(?P<ref>[^|\s]+)\|(?P<code>[A-Za-z]+)\|(?P<loc>[^|]*)\|(?P<coords>[^|]*)"
    r"(?:\|(?P<contact>[^|]*)\|(?P<safe>[01]))?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SOS_RE = re.compile(r"^\s*SOS!?\s+(?P<ref>[A-Za-z0-9-]+)\s*(?P<rest>.*)$", re.IGNORECASE | re.DOTALL)
_COORD_RE = re.compile(r"(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_CODES = {
    "V": CaseType.VIOLENCE,
    "A": CaseType.CARE,
    "C": CaseType.COUNSELING,
    "SOS": CaseType.SOS,
}


def _coords(text: str):
    m = _COORD_RE.search(text or "")
    if not m:
        return None, None
    lat, lon = float(m.group(1)), float(m.group(2))
    if -90 <= lat <= 90 and -180 <= lon <= 180:
        return lat, lon
    return None, None


def _phone(raw: str) -> str:
    try:
        return normalize_ke_phone(raw or "")
    except ValueError:
        return ""


def parse_sms(text: str):
    """Returns a dict ready for services.intake.intake_case(), or None if unrecognised."""
    if not text:
        return None

    m = _REPORT_RE.match(text)
    if m:
        ref = m.group("ref").upper()
        ctype = _CODES.get(m.group("code").upper())
        if not ctype or not _REF_RE.match(ref):
            return None
        lat, lon = _coords(m.group("coords"))
        return {
            "case_ref": ref,
            "type": ctype,
            "location_text": m.group("loc").strip()[:200],
            "lat": lat,
            "lon": lon,
            "contact_phone": _phone(m.group("contact")),
            "safe_to_call": m.group("safe") == "1",
        }

    m = _SOS_RE.match(text)
    if m:
        ref = m.group("ref").upper()
        if not _REF_RE.match(ref):
            return None
        rest = m.group("rest")
        lat, lon = _coords(rest[rest.lower().find("q="):] if "q=" in rest.lower() else "")
        loc = _URL_RE.sub("", rest).strip()
        return {
            "case_ref": ref,
            "type": CaseType.SOS,
            "location_text": loc[:200],
            "lat": lat,
            "lon": lon,
            "contact_phone": "",
            "safe_to_call": False,
        }

    return None

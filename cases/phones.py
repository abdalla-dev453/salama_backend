import re


def normalize_ke_phone(raw: str) -> str:
    """
    '0712 345 678' / '254712345678' / '+254712345678' -> '+254712345678'.
    Empty input -> ''. Anything that is not a Kenyan mobile number -> ValueError.
    """
    s = re.sub(r"[\s\-()]", "", raw or "")
    if not s:
        return ""
    if s.startswith("+254"):
        rest = s[4:]
    elif s.startswith("254"):
        rest = s[3:]
    elif s.startswith("0"):
        rest = s[1:]
    else:
        raise ValueError("not a Kenyan number")
    if re.fullmatch(r"[17]\d{8}", rest):
        return "+254" + rest
    raise ValueError("not a Kenyan number")

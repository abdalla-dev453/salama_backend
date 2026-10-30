"""
Cases only store a free-text location ("Ukunda, near the market"). For reports we
map that text onto the main Kwale areas. Anything else becomes "Other".
Edit this list when Utetezi wants more detail (wards).
"""
AREAS = [
    ("Ukunda", ["ukunda", "diani"]),
    ("Msambweni", ["msambweni", "gazi", "funzi"]),
    ("Lunga Lunga", ["lunga lunga", "lungalunga", "vanga"]),
    ("Kinango", ["kinango", "samburu", "mackinnon"]),
    ("Kwale town", ["kwale town", "matuga", "kwale"]),
]


def area_for(text: str) -> str:
    t = (text or "").lower()
    for name, keys in AREAS:
        if any(k in t for k in keys):
            return name
    return "Other"

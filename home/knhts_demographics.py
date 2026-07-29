"""
KNHTS / KPS.A Client Registration demographics helpers.

Aligns local patient registration with Kenya Patient Summary (KPS.A) and
KNHTS terminology bindings for sex and contact-person role.
"""

# KPSPatientGender / HL7 Administrative Gender (required binding)
GENDER_CHOICES = [
    ('male', 'Male'),
    ('female', 'Female'),
    ('other', 'Other'),
    ('unknown', 'Unknown'),
]

GENDER_LEGACY_MAP = {
    'M': 'male',
    'F': 'female',
    'O': 'other',
    'N': 'unknown',
    'male': 'male',
    'female': 'female',
    'other': 'other',
    'unknown': 'unknown',
}

# Government-issued identifier types (KPS.A identifier + SHA CR)
ID_TYPE_CHOICES = [
    ('NATIONAL_ID', 'National ID'),
    ('PASSPORT', 'Passport'),
    ('BIRTH_CERTIFICATE', 'Birth Certificate'),
    ('ALIEN_ID', 'Alien ID'),
]

ID_TYPE_TO_SHA = {
    'NATIONAL_ID': 'National ID',
    'PASSPORT': 'Passport',
    'BIRTH_CERTIFICATE': 'Birth Certificate',
    'ALIEN_ID': 'Alien ID',
}

SHA_TO_ID_TYPE = {v.lower(): k for k, v in ID_TYPE_TO_SHA.items()}
SHA_TO_ID_TYPE.update({
    'national id': 'NATIONAL_ID',
    'passport': 'PASSPORT',
    'birth certificate': 'BIRTH_CERTIFICATE',
    'alien id': 'ALIEN_ID',
})

# KPSPatientContactRelationship (HL7 v2-0131 subset used for registration)
CONTACT_ROLE_CHOICES = [
    ('N', 'Next-of-Kin'),
    ('C', 'Emergency Contact'),
    ('CP', 'Contact Person'),
    ('EP', 'Emergency Contact Person'),
    ('U', 'Unknown'),
]

# Kenya 47 counties (Kenya Counties Extension / KPS.A address.county)
KENYA_COUNTIES = [
    'Baringo', 'Bomet', 'Bungoma', 'Busia', 'Elgeyo-Marakwet', 'Embu',
    'Garissa', 'Homa Bay', 'Isiolo', 'Kajiado', 'Kakamega', 'Kericho',
    'Kiambu', 'Kilifi', 'Kirinyaga', 'Kisii', 'Kisumu', 'Kitui',
    'Kwale', 'Laikipia', 'Lamu', 'Machakos', 'Makueni', 'Mandera',
    'Marsabit', 'Meru', 'Migori', 'Mombasa', 'Murang\'a', 'Nairobi',
    'Nakuru', 'Nandi', 'Narok', 'Nyamira', 'Nyandarua', 'Nyeri',
    'Samburu', 'Siaya', 'Taita-Taveta', 'Tana River', 'Tharaka-Nithi',
    'Trans Nzoia', 'Turkana', 'Uasin Gishu', 'Vihiga', 'Wajir', 'West Pokot',
]

COUNTY_CHOICES = [('', '---------')] + [(c, c) for c in KENYA_COUNTIES]


def map_gender_to_knhts(value):
    """Normalize any gender/sex string to a KNHTS administrative-gender code."""
    if value is None:
        return 'unknown'
    raw = str(value).strip()
    if not raw:
        return 'unknown'
    if raw in GENDER_LEGACY_MAP:
        return GENDER_LEGACY_MAP[raw]
    lower = raw.lower()
    if lower in GENDER_LEGACY_MAP:
        return GENDER_LEGACY_MAP[lower]
    if lower.startswith('m'):
        return 'male'
    if lower.startswith('f'):
        return 'female'
    if lower in ('o', 'other'):
        return 'other'
    return 'unknown'


def map_sha_identification_type(value):
    """Map SHA/CR identification_type labels to local id_type codes."""
    if not value:
        return 'NATIONAL_ID'
    key = str(value).strip().lower()
    return SHA_TO_ID_TYPE.get(key, 'NATIONAL_ID')


def format_residence_location(*, village='', ward='', sub_county='', county='', postal_address=''):
    """Build a single display location string from structured KPS.A address parts."""
    parts = [p for p in (village, ward, sub_county, county) if p]
    if parts:
        return ', '.join(parts)
    return (postal_address or '').strip()

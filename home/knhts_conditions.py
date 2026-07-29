"""
KNHTS / KPS Condition terminology for Problem List & Diagnoses.

Aligns with Kenya Patient Summary Condition profile:
- clinicalStatus (required for problem-list-item)
- verificationStatus
- category (problem-list-item | encounter-diagnosis)
- code via ICD-11 (facility KNHTS / DHA terminology in use in this HMIS)
"""

# http://terminology.hl7.org/CodeSystem/condition-clinical
CLINICAL_STATUS_CHOICES = [
    ('active', 'Active'),
    ('recurrence', 'Recurrence'),
    ('relapse', 'Relapse'),
    ('inactive', 'Inactive'),
    ('remission', 'Remission'),
    ('resolved', 'Resolved'),
]

ACTIVE_CLINICAL_STATUSES = frozenset({'active', 'recurrence', 'relapse'})

# http://terminology.hl7.org/CodeSystem/condition-ver-status
VERIFICATION_STATUS_CHOICES = [
    ('unconfirmed', 'Unconfirmed'),
    ('provisional', 'Provisional'),
    ('differential', 'Differential'),
    ('confirmed', 'Confirmed'),
    ('refuted', 'Refuted'),
    ('entered-in-error', 'Entered in Error'),
]

# http://terminology.hl7.org/CodeSystem/condition-category
CATEGORY_CHOICES = [
    ('problem-list-item', 'Problem List Item'),
    ('encounter-diagnosis', 'Encounter Diagnosis'),
]

# FHIR ConditionSeverity / KPS Condition Severity (preferred subset)
SEVERITY_CHOICES = [
    ('', '---------'),
    ('mild', 'Mild'),
    ('moderate', 'Moderate'),
    ('severe', 'Severe'),
]

HISTORY_ACTION_CHOICES = [
    ('created', 'Created'),
    ('updated', 'Updated'),
    ('status_changed', 'Status Changed'),
    ('resolved', 'Resolved'),
    ('reactivated', 'Reactivated'),
    ('entered_in_error', 'Entered in Error'),
]

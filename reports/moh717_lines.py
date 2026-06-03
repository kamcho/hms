"""MOH 717 — Monthly Service Workload Report (Outpatient Services)."""

# category: section | data | total | summary
MOH717_LINES = [
    {'row_key': 'sec_a1', 'code': '', 'description': 'A.1 GENERAL OUTPATIENTS (FILTER CLINICS)', 'category': 'section', 'sort_order': 100},
    {'row_key': 'a1_1', 'code': 'A.1.1', 'description': 'Over 5 - Male', 'category': 'data', 'sort_order': 110},
    {'row_key': 'a1_2', 'code': 'A.1.2', 'description': 'Over 5 - Female', 'category': 'data', 'sort_order': 120},
    {'row_key': 'a1_3', 'code': 'A.1.3', 'description': 'Children Under 5 - Male', 'category': 'data', 'sort_order': 130},
    {'row_key': 'a1_4', 'code': 'A.1.4', 'description': 'Children Under 5 - Female', 'category': 'data', 'sort_order': 140},
    {'row_key': 'a1_5', 'code': 'A.1.5', 'description': 'Over 60 years', 'category': 'data', 'sort_order': 150},
    {'row_key': 'a1_total', 'code': 'A.1.5', 'description': 'TOTAL GENERAL OUTPATIENTS', 'category': 'total', 'sort_order': 160},

    {'row_key': 'sec_a2', 'code': '', 'description': 'A.2 CASUALTY', 'category': 'section', 'sort_order': 200},
    {'row_key': 'a2_1', 'code': 'A.2', 'description': 'Casualty', 'category': 'data', 'sort_order': 210},

    {'row_key': 'sec_a3', 'code': '', 'description': 'A.3 SPECIAL CLINICS (if recorded separately from General Filter Clinics)', 'category': 'section', 'sort_order': 300},
    {'row_key': 'a3_1', 'code': 'A.3.1', 'description': 'E.N.T. Clinic', 'category': 'data', 'sort_order': 310},
    {'row_key': 'a3_2', 'code': 'A.3.2', 'description': 'Eye Clinic', 'category': 'data', 'sort_order': 320},
    {'row_key': 'a3_3', 'code': 'A.3.3', 'description': 'TB and Leprosy', 'category': 'data', 'sort_order': 330},
    {'row_key': 'a3_4', 'code': 'A.3.4', 'description': 'Comprehensive Care Clinic (CCC)', 'category': 'data', 'sort_order': 340},
    {'row_key': 'a3_5', 'code': 'A.3.5', 'description': 'Psychiatry', 'category': 'data', 'sort_order': 350},
    {'row_key': 'a3_6', 'code': 'A.3.6', 'description': 'Orthopaedic Clinic', 'category': 'data', 'sort_order': 360},
    {'row_key': 'a3_7', 'code': 'A.3.7', 'description': 'Occupational Therapy Clinic', 'category': 'data', 'sort_order': 370},
    {'row_key': 'a3_8', 'code': 'A.3.8', 'description': 'Physiotherapy Clinic', 'category': 'data', 'sort_order': 380},
    {'row_key': 'a3_9', 'code': 'A.3.9', 'description': 'Medical Clinics', 'category': 'data', 'sort_order': 390},
    {'row_key': 'a3_10', 'code': 'A.3.10', 'description': 'Surgical Clinics', 'category': 'data', 'sort_order': 400},
    {'row_key': 'a3_11', 'code': 'A.3.11', 'description': 'Paediatrics', 'category': 'data', 'sort_order': 410},
    {'row_key': 'a3_12', 'code': 'A.3.12', 'description': 'Obstetrics/Gynaecology', 'category': 'data', 'sort_order': 420},
    {'row_key': 'a3_13', 'code': 'A.3.13', 'description': 'Nutrition Clinic', 'category': 'data', 'sort_order': 430},
    {'row_key': 'a3_14', 'code': 'A.3.14', 'description': 'Oncology Clinic', 'category': 'data', 'sort_order': 440},
    {'row_key': 'a3_15', 'code': 'A.3.15', 'description': 'Renal Clinic', 'category': 'data', 'sort_order': 450},
    {'row_key': 'a3_16', 'code': 'A.3.16', 'description': 'All other Special Clinics', 'category': 'data', 'sort_order': 460},
    {'row_key': 'a3_total', 'code': 'A.3.8', 'description': 'TOTAL SPECIAL CLINICS', 'category': 'total', 'sort_order': 470},

    {'row_key': 'sec_a4', 'code': '', 'description': 'A.4 MCH/FP CLIENTS', 'category': 'section', 'sort_order': 500},
    {'row_key': 'a4_1', 'code': 'A.4.1', 'description': 'CWC Attendances (Child Welfare Clinic)', 'category': 'data', 'sort_order': 510},
    {'row_key': 'a4_2', 'code': 'A.4.2', 'description': 'ANC Attendances (Antenatal Care)', 'category': 'data', 'sort_order': 520},
    {'row_key': 'a4_3', 'code': 'A.4.3', 'description': 'PNC Attendances (Postnatal Care)', 'category': 'data', 'sort_order': 530},
    {'row_key': 'a4_4', 'code': 'A.4.4', 'description': 'FP Attendances (Family Planning)', 'category': 'data', 'sort_order': 540},
    {'row_key': 'a4_total', 'code': 'A.4.5', 'description': 'TOTAL MCH/FP', 'category': 'total', 'sort_order': 550},

    {'row_key': 'sec_a5', 'code': '', 'description': 'A.5 DENTAL CLINIC', 'category': 'section', 'sort_order': 600},
    {'row_key': 'a5_1', 'code': 'A.5.1', 'description': 'Attendances (Excluding fillings and extractions)', 'category': 'data', 'sort_order': 610},
    {'row_key': 'a5_2', 'code': 'A.5.2', 'description': 'Fillings', 'category': 'data', 'sort_order': 620},
    {'row_key': 'a5_3', 'code': 'A.5.3', 'description': 'Extractions', 'category': 'data', 'sort_order': 630},
    {'row_key': 'a5_total', 'code': 'A.5.4', 'description': 'TOTAL DENTAL SERVICES', 'category': 'total', 'sort_order': 640},

    {'row_key': 'a6_total', 'code': 'A.6', 'description': 'TOTAL OUTPATIENT SERVICES (= A.1.5 + A.2 + A.3.7 + A.4.5 + A.5.4)', 'category': 'summary', 'sort_order': 700},
    {'row_key': 'a7_1', 'code': 'A.7', 'description': 'MEDICAL EXAMINATIONS (except p3)', 'category': 'data', 'sort_order': 710},
    {'row_key': 'a8_1', 'code': 'A.8', 'description': 'MEDICAL REPORTS (incl. P3, compensation, insurance, etc.)', 'category': 'data', 'sort_order': 720},
    {'row_key': 'a9_1', 'code': 'A.9', 'description': 'DRESSINGS', 'category': 'data', 'sort_order': 730},
    {'row_key': 'a10_1', 'code': 'A.10', 'description': 'REMOVAL OF STITCHES', 'category': 'data', 'sort_order': 740},
    {'row_key': 'a11_1', 'code': 'A.11', 'description': 'INJECTIONS', 'category': 'data', 'sort_order': 750},
    {'row_key': 'a12_1', 'code': 'A.12', 'description': 'STITCHING', 'category': 'data', 'sort_order': 760},
]

MOH717_FORM_NOTE = (
    'Use NS for No Service and NR for Not Recorded where applicable. '
    'Submit monthly returns by the deadline set by the county.'
)

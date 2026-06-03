"""
MOH 710 — NVIP Integrated Immunization Summary (Section A row definitions).
Each entry: row_key, antigen, age_group_label, sort_order, section
"""

MOH710_SECTION_A_LINES = [
    # BCG
    {'row_key': 'bcg_under_1', 'antigen': 'BCG', 'age_group': 'Under 1 Year', 'sort_order': 10},
    {'row_key': 'bcg_above_1', 'antigen': 'BCG', 'age_group': 'Above 1 Year', 'sort_order': 11},
    # OPV birth
    {'row_key': 'opv_birth_within_2w', 'antigen': 'OPV (Birth dose)', 'age_group': 'Within 2 weeks', 'sort_order': 20},
    {'row_key': 'opv_birth_above_2w', 'antigen': 'OPV (Birth dose)', 'age_group': 'Above 2 weeks', 'sort_order': 21},
    # OPV 1-3
    {'row_key': 'opv1_under_1', 'antigen': 'OPV1', 'age_group': 'Under 1 Year', 'sort_order': 30},
    {'row_key': 'opv1_above_1', 'antigen': 'OPV1', 'age_group': 'Above 1 Year', 'sort_order': 31},
    {'row_key': 'opv2_under_1', 'antigen': 'OPV2', 'age_group': 'Under 1 Year', 'sort_order': 32},
    {'row_key': 'opv2_above_1', 'antigen': 'OPV2', 'age_group': 'Above 1 Year', 'sort_order': 33},
    {'row_key': 'opv3_under_1', 'antigen': 'OPV3', 'age_group': 'Under 1 Year', 'sort_order': 34},
    {'row_key': 'opv3_above_1', 'antigen': 'OPV3', 'age_group': 'Above 1 Year', 'sort_order': 35},
    # IPV
    {'row_key': 'ipv1_under_1', 'antigen': 'IPV 1', 'age_group': 'Under 1 Year', 'sort_order': 40},
    {'row_key': 'ipv1_above_1', 'antigen': 'IPV 1', 'age_group': 'Above 1 Year', 'sort_order': 41},
    {'row_key': 'ipv2_under_1', 'antigen': 'IPV 2', 'age_group': 'Under 1 Year', 'sort_order': 42},
    {'row_key': 'ipv2_above_1', 'antigen': 'IPV 2', 'age_group': 'Above 1 Year', 'sort_order': 43},
    # Pentavalent DPT+HIB+HEPB
    {'row_key': 'pent1_under_1', 'antigen': 'DPT+HIB+HEPB 1', 'age_group': 'Under 1 Year', 'sort_order': 50},
    {'row_key': 'pent1_above_1', 'antigen': 'DPT+HIB+HEPB 1', 'age_group': 'Above 1 Year', 'sort_order': 51},
    {'row_key': 'pent2_under_1', 'antigen': 'DPT+HIB+HEPB 2', 'age_group': 'Under 1 Year', 'sort_order': 52},
    {'row_key': 'pent2_above_1', 'antigen': 'DPT+HIB+HEPB 2', 'age_group': 'Above 1 Year', 'sort_order': 53},
    {'row_key': 'pent3_under_1', 'antigen': 'DPT+HIB+HEPB 3', 'age_group': 'Under 1 Year', 'sort_order': 54},
    {'row_key': 'pent3_above_1', 'antigen': 'DPT+HIB+HEPB 3', 'age_group': 'Above 1 Year', 'sort_order': 55},
    # Pneumococcal
    {'row_key': 'pcv1_under_1', 'antigen': 'Pneumococcal 1', 'age_group': 'Under 1 Year', 'sort_order': 60},
    {'row_key': 'pcv1_above_1', 'antigen': 'Pneumococcal 1', 'age_group': 'Above 1 Year', 'sort_order': 61},
    {'row_key': 'pcv2_under_1', 'antigen': 'Pneumococcal 2', 'age_group': 'Under 1 Year', 'sort_order': 62},
    {'row_key': 'pcv2_above_1', 'antigen': 'Pneumococcal 2', 'age_group': 'Above 1 Year', 'sort_order': 63},
    {'row_key': 'pcv3_under_1', 'antigen': 'Pneumococcal 3', 'age_group': 'Under 1 Year', 'sort_order': 64},
    {'row_key': 'pcv3_above_1', 'antigen': 'Pneumococcal 3', 'age_group': 'Above 1 Year', 'sort_order': 65},
    # Rota (under 1 only on form)
    {'row_key': 'rota1_under_1', 'antigen': 'Rota 1', 'age_group': 'Under 1 Year', 'sort_order': 70},
    {'row_key': 'rota2_under_1', 'antigen': 'Rota 2', 'age_group': 'Under 1 Year', 'sort_order': 71},
    {'row_key': 'rota3_under_1', 'antigen': 'Rota 3', 'age_group': 'Under 1 Year', 'sort_order': 72},
    # Vitamin A 6-11 months
    {'row_key': 'vit_a_6_11', 'antigen': 'Vitamin A', 'age_group': 'At 6-11 Months (100,000 IU)', 'sort_order': 80},
    # Malaria vaccine
    {'row_key': 'mal1_under_1', 'antigen': 'Malaria Vaccine 1', 'age_group': 'Under 1 Year', 'sort_order': 90},
    {'row_key': 'mal1_above_1', 'antigen': 'Malaria Vaccine 1', 'age_group': 'Above 1 Year', 'sort_order': 91},
    {'row_key': 'mal2_under_1', 'antigen': 'Malaria Vaccine 2', 'age_group': 'Under 1 Year', 'sort_order': 92},
    {'row_key': 'mal2_above_1', 'antigen': 'Malaria Vaccine 2', 'age_group': 'Above 1 Year', 'sort_order': 93},
    {'row_key': 'mal3_under_1', 'antigen': 'Malaria Vaccine 3', 'age_group': 'Under 1 Year', 'sort_order': 94},
    {'row_key': 'mal3_above_1', 'antigen': 'Malaria Vaccine 3', 'age_group': 'Above 1 Year', 'sort_order': 95},
    {'row_key': 'mal4_2_3y', 'antigen': 'Malaria Vaccine 4', 'age_group': 'At 2-3 years', 'sort_order': 96},
    {'row_key': 'mal4_above_3y', 'antigen': 'Malaria Vaccine 4', 'age_group': 'Above 3 years', 'sort_order': 97},
    # Yellow fever, MR
    {'row_key': 'yf_under_1', 'antigen': 'Yellow fever', 'age_group': 'Under 1 Year', 'sort_order': 100},
    {'row_key': 'yf_above_1', 'antigen': 'Yellow fever', 'age_group': 'Above 1 Year', 'sort_order': 101},
    {'row_key': 'mr1_under_1', 'antigen': 'MR 1', 'age_group': 'Under 1 Year', 'sort_order': 110},
    {'row_key': 'mr1_above_1', 'antigen': 'MR 1', 'age_group': 'Above 1 Year', 'sort_order': 111},
    {'row_key': 'mr2_18_24m', 'antigen': 'MR 2', 'age_group': 'At 1½ - 2 Years', 'sort_order': 112},
    {'row_key': 'mr2_above_2y', 'antigen': 'MR 2', 'age_group': 'Above 2 Years', 'sort_order': 113},
    # Typhoid, FIC, Vit A 12-59
    {'row_key': 'tcv_under_1', 'antigen': 'Typhoid Conjugate Vaccine', 'age_group': 'Under 1 Year', 'sort_order': 120},
    {'row_key': 'tcv_above_1', 'antigen': 'Typhoid Conjugate Vaccine', 'age_group': 'Above 1 Year', 'sort_order': 121},
    {'row_key': 'fic_1y', 'antigen': 'Fully Immunized Child (FIC) at 1 year', 'age_group': '', 'sort_order': 130},
    {'row_key': 'vit_a_12_59', 'antigen': 'Vitamin A', 'age_group': 'At 12-59 Months (200,000 IU)', 'sort_order': 140},
    # Td pregnant
    {'row_key': 'td_pw_dose1', 'antigen': 'Tetanus Diphtheria (pregnant women)', 'age_group': '1st Dose', 'sort_order': 150},
    {'row_key': 'td_pw_dose2', 'antigen': 'Tetanus Diphtheria (pregnant women)', 'age_group': '2nd Dose', 'sort_order': 151},
    {'row_key': 'td_pw_dose3', 'antigen': 'Tetanus Diphtheria (pregnant women)', 'age_group': '3rd Dose', 'sort_order': 152},
    {'row_key': 'td_pw_dose4', 'antigen': 'Tetanus Diphtheria (pregnant women)', 'age_group': '4th Dose', 'sort_order': 153},
    {'row_key': 'td_pw_dose5', 'antigen': 'Tetanus Diphtheria (pregnant women)', 'age_group': '5th Dose', 'sort_order': 154},
    {'row_key': 'tt_trauma', 'antigen': 'Tetanus Toxoid (Trauma)', 'age_group': '', 'sort_order': 160},
    # HPV
    {'row_key': 'hpv_dose1', 'antigen': 'HPV Vaccine', 'age_group': '1st Dose - 10 years', 'sort_order': 170},
    {'row_key': 'hpv_dose2', 'antigen': 'HPV Vaccine', 'age_group': '2nd Dose (≥6 months after dose 1)', 'sort_order': 171},
    # Other indicators
    {'row_key': 'aefi', 'antigen': 'Adverse Events Following Immunization', 'age_group': '', 'sort_order': 180},
    {'row_key': 'squint_u1', 'antigen': 'Squint/White Eye reflection', 'age_group': 'Under 1 Year', 'sort_order': 190},
]

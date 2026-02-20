from django.db import models
from django.conf import settings
from django.utils import timezone
from home.models import Patient
from inpatient.models import Admission


class Pregnancy(models.Model):
    """Main pregnancy record - tracks entire maternity journey"""
    
    STATUS_CHOICES = [
        ('Active', 'Active Pregnancy'),
        ('Delivered', 'Delivered'),
        ('Miscarriage', 'Miscarriage'),
        ('Abortion', 'Abortion'),
        ('Ectopic', 'Ectopic Pregnancy'),
    ]
    
    BLOOD_GROUP_CHOICES = [
        ('A+', 'A Positive'),
        ('A-', 'A Negative'),
        ('B+', 'B Positive'),
        ('B-', 'B Negative'),
        ('O+', 'O Positive'),
        ('O-', 'O Negative'),
        ('AB+', 'AB Positive'),
        ('AB-', 'AB Negative'),
    ]
    
    # Patient Information
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='pregnancies')
    registration_date = models.DateField(default=timezone.now)
    
    # Pregnancy Details
    lmp = models.DateField(verbose_name="Last Menstrual Period")
    edd = models.DateField(verbose_name="Expected Delivery Date")
    gravida = models.PositiveIntegerField(help_text="Total number of pregnancies")
    para = models.PositiveIntegerField(help_text="Number of deliveries after 28 weeks")
    abortion = models.PositiveIntegerField(default=0, help_text="Number of abortions/miscarriages")
    living = models.PositiveIntegerField(default=0, help_text="Number of living children")
    
    # Medical History
    blood_group = models.CharField(max_length=3, choices=BLOOD_GROUP_CHOICES, blank=True)
    allergies = models.TextField(blank=True, null=True)
    previous_cs = models.BooleanField(default=False, verbose_name="Previous C-Section")
    is_multiple_gestation = models.BooleanField(default=False, verbose_name="Multiple Gestation (Twins/Triplets)")
    chronic_conditions = models.TextField(blank=True, null=True, help_text="Diabetes, Hypertension, etc.")
    
    # Current Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    risk_level = models.CharField(max_length=20, choices=[
        ('Low', 'Low Risk'),
        ('Moderate', 'Moderate Risk'),
        ('High', 'High Risk'),
    ], default='Low')
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='pregnancies_created')
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = 'Pregnancies'
    
    def __str__(self):
        return f"{self.patient.full_name} - Pregnancy {self.id} ({self.status})"
    
    @property
    def gestational_age_weeks(self):
        """Calculate current gestational age in weeks"""
        if self.status != 'Active':
            return None
        delta = timezone.now().date() - self.lmp
        return delta.days // 7
    
    @property
    def para_code(self):
        """Return GPAL notation"""
        return f"G{self.gravida}P{self.para}A{self.abortion}L{self.living}"

    def get_active_alerts(self):
        """Retrieve list of clinical alerts for this pregnancy"""
        alerts = []
        
        # 1. Chronic Conditions
        if self.chronic_conditions:
            alerts.append({'type': 'warning', 'category': 'Medical History', 'message': f"Chronic Conditions: {self.chronic_conditions}"})
        
        if self.previous_cs:
            alerts.append({'type': 'danger', 'category': 'Obstetric History', 'message': "Previous C-Section - Risk of Rupture"})

        if self.is_multiple_gestation:
            alerts.append({'type': 'danger', 'category': 'Pregnancy Type', 'message': "Multiple Gestation (Twins/Multiples) - High Risk"})

        # 2. Get latest visit for current vitals/tests
        latest_visit = self.anc_visits.filter(service_received=True).order_by('-visit_date', '-created_at').first()
        
        if latest_visit:
            # BP Alert
            if latest_visit.bp_systolic and latest_visit.bp_systolic >= 140 or \
               latest_visit.bp_diastolic and latest_visit.bp_diastolic >= 90:
                alerts.append({
                    'type': 'danger',
                    'category': 'Hypertension',
                    'message': f"High BP detected: {latest_visit.bp_systolic}/{latest_visit.bp_diastolic} mmHg"
                })
            
            # Preeclampsia Markers
            if latest_visit.urine_protein in ['+', '++', '+++']:
                alerts.append({
                    'type': 'danger', 
                    'category': 'Preeclampsia', 
                    'message': f"Proteinuria detected ({latest_visit.urine_protein})"
                })

            # HIV Status
            if latest_visit.hiv_status == 'Positive':
                alerts.append({'type': 'danger', 'category': 'Infectious Disease', 'message': "HIV Positive - Follow PMTCT Protocol"})

            # Growth Deviation (Fundal Height vs Gestational Age)
            if latest_visit.fundal_height and latest_visit.gestational_age:
                # Rule of thumb: +/- 3cm deviation is significant after 20 weeks
                if latest_visit.gestational_age >= 20:
                    diff = abs(latest_visit.fundal_height - latest_visit.gestational_age)
                    if diff > 3:
                        alerts.append({
                            'type': 'warning',
                            'category': 'Growth',
                            'message': f"Fundal height deviation ({latest_visit.fundal_height}cm at {latest_visit.gestational_age} weeks)"
                        })

        # 3. Overall Risk Level
        if self.risk_level == 'High':
            alerts.append({'type': 'danger', 'category': 'Classification', 'message': "Patient Classified as HIGH RISK"})
            
        return alerts


class AntenatalVisit(models.Model):
    """Individual ANC checkup records"""
    
    pregnancy = models.ForeignKey(Pregnancy, on_delete=models.CASCADE, related_name='anc_visits')
    visit_date = models.DateField(default=timezone.now)
    visit_number = models.PositiveIntegerField(null=True, blank=True)
    gestational_age = models.PositiveIntegerField(help_text="Weeks", null=True, blank=True)
    service_received = models.BooleanField(default=False)
    is_closed = models.BooleanField(default=False, help_text="Whether this visit record is complete/closed")
    
    # Vitals
    weight = models.DecimalField(max_digits=5, decimal_places=2, help_text="kg", null=True, blank=True)
    bp_systolic = models.PositiveIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveIntegerField(null=True, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, help_text="°C", null=True, blank=True)
    
    # Obstetric Examination
    fundal_height = models.PositiveIntegerField(help_text="cm", null=True, blank=True)
    fetal_heart_rate = models.PositiveIntegerField(help_text="bpm", null=True, blank=True)
    fetal_presentation = models.CharField(max_length=50, blank=True, choices=[
        ('Cephalic', 'Cephalic (Head down)'),
        ('Breech', 'Breech'),
        ('Transverse', 'Transverse'),
        ('Oblique', 'Oblique'),
    ])
    fetal_movements = models.CharField(max_length=20, choices=[
        ('Active', 'Active'),
        ('Reduced', 'Reduced'),
        ('Absent', 'Absent'),
    ], blank=True)
    
    # Lab Results
    hemoglobin = models.DecimalField(max_digits=4, decimal_places=1, help_text="g/dL", null=True, blank=True)
    blood_sugar = models.DecimalField(max_digits=5, decimal_places=2, help_text="mmol/L", null=True, blank=True)
    urine_protein = models.CharField(max_length=10, blank=True, help_text="Negative, +, ++, +++")
    hiv_status = models.CharField(max_length=20, choices=[
        ('Negative', 'Negative'),
        ('Positive', 'Positive'),
        ('Unknown', 'Unknown'),
    ], blank=True)
    
    # Treatment & Advice
    iron_supplements = models.BooleanField(default=False)
    folate_supplements = models.BooleanField(default=False)
    deworming = models.BooleanField(default=False)
    tetanus_toxoid = models.BooleanField(default=False)
    
    complaints = models.TextField(blank=True, null=True)
    findings = models.TextField(blank=True, null=True)
    plan = models.TextField(blank=True, null=True)
    next_visit_date = models.DateField(null=True, blank=True)
    
    # Metadata
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-visit_date']
        unique_together = ['pregnancy', 'visit_number']
    
    def __str__(self):
        return f"ANC Visit {self.visit_number} - {self.pregnancy.patient.full_name}"


class LaborDelivery(models.Model):
    """Labor and delivery record"""
    
    LABOR_ONSET_CHOICES = [
        ('Spontaneous', 'Spontaneous'),
        ('Induced', 'Induced'),
        ('Elective CS', 'Elective C-Section'),
    ]
    
    DELIVERY_MODE_CHOICES = [
        ('SVD', 'Spontaneous Vaginal Delivery'),
        ('AVD', 'Assisted Vaginal Delivery (Vacuum/Forceps)'),
        ('Emergency CS', 'Emergency C-Section'),
        ('Elective CS', 'Elective C-Section'),
    ]
    
    pregnancy = models.OneToOneField(Pregnancy, on_delete=models.CASCADE, related_name='delivery')
    admission = models.OneToOneField(Admission, on_delete=models.SET_NULL, null=True, blank=True, related_name='delivery')
    visit = models.OneToOneField('home.Visit', on_delete=models.SET_NULL, null=True, blank=True, related_name='labor_delivery')
    
    # Admission Details
    admission_date = models.DateTimeField(default=timezone.now)
    gestational_age_at_delivery = models.PositiveIntegerField(help_text="Weeks")
    
    # Labor Details
    labor_onset = models.CharField(max_length=20, choices=LABOR_ONSET_CHOICES)
    rupture_of_membranes = models.DateTimeField(null=True, blank=True)
    labor_duration = models.DurationField(null=True, blank=True, help_text="Total labor duration")
    
    # Delivery
    delivery_datetime = models.DateTimeField()
    delivery_mode = models.CharField(max_length=30, choices=DELIVERY_MODE_CHOICES)
    delivery_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='deliveries_conducted')
    
    # Complications
    maternal_complications = models.TextField(blank=True, null=True, help_text="PPH, tears, retained placenta, etc.")
    episiotomy = models.BooleanField(default=False)
    perineal_tear = models.CharField(max_length=50, blank=True, help_text="Degree of tear")
    
    # Blood Loss
    estimated_blood_loss = models.PositiveIntegerField(help_text="mL", null=True, blank=True)
    blood_transfusion = models.BooleanField(default=False)
    
    # Placenta
    placenta_delivery = models.CharField(max_length=50, choices=[
        ('Complete', 'Complete'),
        ('Incomplete', 'Incomplete'),
        ('Manual Removal', 'Manual Removal Required'),
    ], blank=True)
    
    # Mother's Condition
    mother_condition = models.CharField(max_length=50, choices=[
        ('Stable', 'Stable'),
        ('ICU', 'Transferred to ICU'),
        ('Deceased', 'Maternal Death'),
    ], default='Stable')
    
    # Notes
    delivery_notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = 'Labor & Delivery Records'
    
    def __str__(self):
        return f"Delivery - {self.pregnancy.patient.full_name} - {self.delivery_datetime.date()}"


class Newborn(models.Model):
    """Newborn baby record"""
    
    GENDER_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('A', 'Ambiguous'),
    ]
    
    delivery = models.ForeignKey(LaborDelivery, on_delete=models.CASCADE, related_name='newborns')
    patient_profile = models.OneToOneField('home.Patient', on_delete=models.SET_NULL, null=True, blank=True, related_name='newborn_clinical_record')
    
    # Basic Info
    baby_number = models.PositiveIntegerField(default=1, help_text="For multiple births")
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES)
    birth_datetime = models.DateTimeField()
    
    # Birth Details
    birth_weight = models.DecimalField(max_digits=5, decimal_places=3, help_text="kg")
    birth_length = models.DecimalField(max_digits=4, decimal_places=1, help_text="cm", null=True, blank=True)
    head_circumference = models.DecimalField(max_digits=4, decimal_places=1, help_text="cm", null=True, blank=True)
    
    # APGAR Scores
    apgar_1min = models.PositiveIntegerField()
    apgar_5min = models.PositiveIntegerField()
    apgar_10min = models.PositiveIntegerField(null=True, blank=True)
    
    # Resuscitation
    resuscitation_required = models.BooleanField(default=False)
    resuscitation_details = models.TextField(blank=True, null=True)
    
    # Condition
    congenital_abnormalities = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=[
        ('Alive', 'Alive and Well'),
        ('NICU', 'Admitted to NICU'),
        ('Stillborn', 'Stillborn'),
        ('Neonatal Death', 'Neonatal Death'),
    ], default='Alive')
    
    # Feeding
    breastfeeding_initiated = models.BooleanField(default=False)
    
    # Immunizations
    bcg_given = models.BooleanField(default=False)
    opv_0_given = models.BooleanField(default=False, verbose_name="OPV 0 Given")
    
    # Notes
    notes = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    
    class Meta:
        ordering = ['baby_number']
    
    def __str__(self):
        return f"Baby {self.baby_number} - {self.delivery.pregnancy.patient.full_name} - {self.get_gender_display()}"




class PostnatalMotherVisit(models.Model):
    """Postnatal checkup for the mother"""
    
    delivery = models.ForeignKey(LaborDelivery, on_delete=models.CASCADE, related_name='mother_pnc_visits')
    visit_date = models.DateField(default=timezone.now)
    visit_day = models.PositiveIntegerField(help_text="Days post-delivery", null=True, blank=True)
    service_received = models.BooleanField(default=False)
    
    # Mother Vitals
    bp_systolic = models.PositiveIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveIntegerField(null=True, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, help_text="°C", null=True, blank=True)
    pulse = models.PositiveIntegerField(help_text="bpm", null=True, blank=True)
    
    # Physical Examination
    uterus_involution = models.CharField(max_length=50, blank=True, help_text="Fundal height")
    lochia = models.CharField(max_length=50, choices=[
        ('Normal', 'Normal'),
        ('Heavy', 'Heavy'),
        ('Offensive', 'Offensive smell'),
    ], blank=True)
    
    breastfeeding_status = models.CharField(max_length=50, choices=[
        ('Exclusive', 'Exclusive Breastfeeding'),
        ('Mixed', 'Mixed Feeding'),
        ('Formula', 'Formula Only'),
        ('Difficulties', 'Breastfeeding Difficulties'),
    ], blank=True)
    
    perineum_wound = models.CharField(max_length=50, choices=[
        ('N/A', 'Not Applicable'),
        ('Healing', 'Healing Well'),
        ('Infected', 'Signs of Infection'),
        ('Dehiscence', 'Wound Dehiscence'),
    ], blank=True)
    
    cs_wound = models.CharField(max_length=50, choices=[
        ('N/A', 'Not Applicable'),
        ('Healing', 'Healing Well'),
        ('Infected', 'Signs of Infection'),
        ('Dehiscence', 'Wound Dehiscence'),
    ], blank=True, help_text="For C-section deliveries")
    
    # Family Planning
    family_planning_counseling = models.BooleanField(default=False)
    contraception_method = models.CharField(max_length=100, blank=True)
    
    # Mental Health
    mood_assessment = models.CharField(max_length=50, choices=[
        ('Normal', 'Normal'),
        ('Baby Blues', 'Baby Blues'),
        ('Concern PPD', 'Concern for Postpartum Depression'),
    ], blank=True)
    
    # Notes
    complaints = models.TextField(blank=True, null=True)
    findings = models.TextField(blank=True, null=True)
    plan = models.TextField(blank=True, null=True)
    next_visit_date = models.DateField(null=True, blank=True)
    
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-visit_date']
        verbose_name = 'Postnatal Mother Visit'
        verbose_name_plural = 'Postnatal Mother Visits'
    
    def __str__(self):
        return f"Mother PNC Day {self.visit_day} - {self.delivery.pregnancy.patient.full_name}"


class PostnatalBabyVisit(models.Model):
    """Postnatal checkup for individual baby - handles multiple births correctly"""
    
    newborn = models.ForeignKey(Newborn, on_delete=models.CASCADE, related_name='pnc_visits')
    visit_date = models.DateField(default=timezone.now)
    visit_day = models.PositiveIntegerField(help_text="Days post-delivery", null=True, blank=True)
    service_received = models.BooleanField(default=False)
    
    # Baby Vitals & Measurements
    weight = models.DecimalField(max_digits=5, decimal_places=3, help_text="kg")
    length = models.DecimalField(max_digits=4, decimal_places=1, help_text="cm", null=True, blank=True)
    head_circumference = models.DecimalField(max_digits=4, decimal_places=1, help_text="cm", null=True, blank=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, help_text="°C", null=True, blank=True)
    
    # Feeding
    feeding_type = models.CharField(max_length=50, choices=[
        ('Exclusive BF', 'Exclusive Breastfeeding'),
        ('Mixed', 'Mixed Feeding'),
        ('Formula', 'Formula Only'),
    ], blank=True)
    feeding_well = models.BooleanField(default=True)
    feeding_difficulties = models.TextField(blank=True, null=True)
    
    # Physical Examination
    umbilical_cord = models.CharField(max_length=50, choices=[
        ('Attached', 'Still Attached - Clean'),
        ('Attached Infected', 'Attached - Signs of Infection'),
        ('Separated', 'Separated - Healing Well'),
        ('Separated Infected', 'Separated - Infected'),
    ], blank=True)
    
    jaundice = models.BooleanField(default=False)
    jaundice_level = models.CharField(max_length=50, blank=True, help_text="Clinical assessment or bilirubin level")
    
    skin_condition = models.CharField(max_length=100, blank=True, help_text="Rashes, infections, etc.")
    eyes = models.CharField(max_length=100, blank=True, help_text="Discharge, conjunctivitis")
    
    # Immunizations given this visit
    vaccines_given = models.TextField(blank=True, null=True, help_text="List vaccines administered")
    
    # Development
    alertness = models.CharField(max_length=50, choices=[
        ('Alert', 'Alert and Active'),
        ('Lethargic', 'Lethargic'),
        ('Unresponsive', 'Unresponsive'),
    ], blank=True)
    
    # Notes
    complaints = models.TextField(blank=True, null=True)
    findings = models.TextField(blank=True, null=True)
    plan = models.TextField(blank=True, null=True)
    next_visit_date = models.DateField(null=True, blank=True)
    
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-visit_date']
        verbose_name = 'Postnatal Baby Visit'
        verbose_name_plural = 'Postnatal Baby Visits'
    
    def __str__(self):
        return f"Baby {self.newborn.baby_number} PNC Day {self.visit_day} - {self.newborn.delivery.pregnancy.patient.full_name}"


class MaternityDischarge(models.Model):
    """Formal clinical closure for mother and baby"""
    
    pregnancy = models.OneToOneField(Pregnancy, on_delete=models.CASCADE, related_name='maternity_discharge')
    discharge_date = models.DateTimeField(default=timezone.now)
    
    # Clinical Outcomes
    mother_condition_at_discharge = models.CharField(max_length=50, choices=[
        ('Stable', 'Healthy / Stable'),
        ('Needs Follow-up', 'Requires Close Follow-up'),
        ('Complicated', 'Complicated Recovery'),
    ], default='Stable')
    
    baby_condition_at_discharge = models.CharField(max_length=100, help_text="Summary of newborn(s) status")
    
    final_diagnosis = models.TextField(blank=True)
    discharge_summary = models.TextField(help_text="Clinical summary of the maternity episode")
    follow_up_plan = models.TextField(help_text="Instructions for postnatal care and return visits")
    
    # Medication on Discharge
    medications_prescribed = models.TextField(blank=True, help_text="Medications given to take home")
    
    # Admin
    discharged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='maternity_discharges_authorized')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Discharge: {self.pregnancy.patient.full_name} ({self.discharge_date.date()})"


class MaternityReferral(models.Model):
    """Tracking outward referrals to other facilities"""
    
    pregnancy = models.ForeignKey(Pregnancy, on_delete=models.CASCADE, related_name='referrals')
    referral_date = models.DateTimeField(default=timezone.now)
    
    # Destination
    referred_to_facility = models.CharField(max_length=200, help_text="Name of the receiving hospital")
    department = models.CharField(max_length=100, blank=True)
    
    # Reason
    reason_for_referral = models.TextField()
    clinical_clinical_summary = models.TextField(help_text="Clinical status and interventions performed")
    urgent = models.BooleanField(default=False)
    
    # Logistics
    transport_mode = models.CharField(max_length=50, choices=[
        ('Ambulance', 'Ambulance'),
        ('Private', 'Private Means'),
        ('Public', 'Public Transport'),
    ], default='Ambulance')
    
    # Admin
    referred_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='maternity_referrals_made')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Referral: {self.pregnancy.patient.full_name} to {self.referred_to_facility}"

class Vaccine(models.Model):
    """Catalog of available vaccines"""
    name = models.CharField(max_length=100, unique=True)
    abbreviation = models.CharField(max_length=20, unique=True, help_text="e.g., BCG, OPV, DPT")
    description = models.TextField(blank=True)
    target_diseases = models.TextField(blank=True)
    route = models.CharField(max_length=50, blank=True, help_text="Oral, Intramuscular, etc.")
    
    def __str__(self):
        return f"{self.name} ({self.abbreviation})"

    class Meta:
        ordering = ['name']


class ImmunizationRecord(models.Model):
    """Tracks specific doses administered to newborns"""
    newborn = models.ForeignKey(Newborn, on_delete=models.CASCADE, related_name='vaccinations', null=True, blank=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name='vaccinations', null=True, blank=True)
    visit = models.ForeignKey(PostnatalBabyVisit, on_delete=models.SET_NULL, null=True, blank=True, related_name='vaccinations')
    vaccine = models.ForeignKey(Vaccine, on_delete=models.CASCADE)
    dose_number = models.PositiveIntegerField(default=1, help_text="1st Dose, 2nd Dose, Booster, etc.")
    date_administered = models.DateField(default=timezone.now)
    batch_number = models.CharField(max_length=50, blank=True)
    
    # Clinical Data
    reaction_observed = models.TextField(blank=True, help_text="Any adverse reactions")
    
    # Follow-up
    next_dose_due = models.DateField(null=True, blank=True)
    
    # Admin
    administered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    facility = models.CharField(max_length=200, blank=True, help_text="Facility where vaccine was given")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-date_administered']
        unique_together = ['newborn', 'vaccine', 'dose_number']
        verbose_name = 'Immunization Record'
        verbose_name_plural = 'Immunization Records'

    def __str__(self):
        return f"{self.vaccine.abbreviation} Dose {self.dose_number}"

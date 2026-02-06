from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from home.models import Patient, Visit, Ward, Bed
from inpatient.models import Admission
from django.utils import timezone

User = get_user_model()

class AdmissionLogicTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(id_number='DOC001', password='password', role='Doctor')
        self.client.login(id_number='DOC001', password='password')
        
        self.patient = Patient.objects.create(
            first_name='Jane', 
            last_name='Doe',
            date_of_birth=timezone.now().date() - timezone.timedelta(days=365*25),
            phone='0787654321',
            location='Mombasa',
            gender='F'
        )
        
        self.ward = Ward.objects.create(name='General Ward', base_charge_per_day=1500)
        self.bed = Bed.objects.create(bed_number='B1', ward=self.ward)

    def test_admission_creates_new_visit(self):
        # Initial visit count
        self.assertEqual(Visit.objects.filter(patient=self.patient).count(), 0)
        
        url = reverse('inpatient:admit_patient', kwargs={'patient_id': self.patient.id})
        data = {
            'ward': self.ward.id,
            'bed': self.bed.id,
            'provisional_diagnosis': 'Test Diagnosis'
        }
        
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302) # Redirects to case folder
        
        # Check if admission exists
        admission = Admission.objects.get(patient=self.patient)
        self.assertEqual(admission.status, 'Admitted')
        
        # Check if visit was created
        visits = Visit.objects.filter(patient=self.patient)
        self.assertEqual(visits.count(), 1)
        visit = visits.first()
        self.assertEqual(visit.visit_type, 'IN-PATIENT')
        self.assertEqual(admission.visit, visit)

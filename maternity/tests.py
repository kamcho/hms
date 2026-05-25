from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from home.models import Patient
from maternity.models import Pregnancy
from datetime import timedelta

User = get_user_model()

class PregnancyEditTestCase(TestCase):
    def setUp(self):
        # Create user
        self.user = User.objects.create_user(
            id_number='12345',
            password='testpassword',
            first_name='Test',
            last_name='Nurse'
        )
        self.client.login(username='12345', password='testpassword')
        
        # Create patient
        self.patient = Patient.objects.create(
            first_name='Jane',
            last_name='Doe',
            date_of_birth=timezone.now().date() - timedelta(days=365*25),
            location='Nairobi',
            gender='F'
        )
        
        # Create pregnancy
        self.pregnancy = Pregnancy.objects.create(
            patient=self.patient,
            lmp=timezone.now().date() - timedelta(days=100),
            edd=timezone.now().date() + timedelta(days=180),
            gravida=2,
            para=1,
            abortion=0,
            living=1,
            blood_group='O+',
            status='Active',
            risk_level='Low',
            created_by=self.user
        )

    def test_edit_pregnancy_details_success(self):
        url = reverse('maternity:pregnancy_detail', kwargs={'pregnancy_id': self.pregnancy.id})
        
        # Post request to edit pregnancy details
        post_data = {
            'edit_pregnancy': '1',
            'lmp': (timezone.now().date() - timedelta(days=90)).strftime('%Y-%m-%d'),
            'edd': (timezone.now().date() + timedelta(days=190)).strftime('%Y-%m-%d'),
            'gravida': 3,
            'para': 2,
            'abortion': 0,
            'living': 2,
            'blood_group': 'A+',
            'previous_cs': 'on', # Checkbox is sent as 'on' when checked
            'is_multiple_gestation': 'on',
            'allergies': 'Penicillin',
            'chronic_conditions': 'None',
            'risk_level': 'High',
            'status': 'Active'
        }
        
        response = self.client.post(url, post_data)
        
        # Should redirect back to detail page on success
        self.assertRedirects(response, url)
        
        # Check that pregnancy has been updated
        self.pregnancy.refresh_from_db()
        self.assertEqual(self.pregnancy.gravida, 3)
        self.assertEqual(self.pregnancy.para, 2)
        self.assertEqual(self.pregnancy.living, 2)
        self.assertEqual(self.pregnancy.blood_group, 'A+')
        self.assertTrue(self.pregnancy.previous_cs)
        self.assertTrue(self.pregnancy.is_multiple_gestation)
        self.assertEqual(self.pregnancy.allergies, 'Penicillin')
        self.assertEqual(self.pregnancy.risk_level, 'High')

    def test_edit_pregnancy_details_validation_failure(self):
        url = reverse('maternity:pregnancy_detail', kwargs={'pregnancy_id': self.pregnancy.id})
        
        # Post request with invalid negative gravida
        post_data = {
            'edit_pregnancy': '1',
            'lmp': (timezone.now().date() - timedelta(days=90)).strftime('%Y-%m-%d'),
            'edd': (timezone.now().date() + timedelta(days=190)).strftime('%Y-%m-%d'),
            'gravida': -5, # Invalid negative number
            'para': 2,
            'abortion': 0,
            'living': 2,
            'blood_group': 'A+',
            'risk_level': 'High',
            'status': 'Active'
        }
        
        response = self.client.post(url, post_data)
        
        # Should NOT redirect, should render the form again with errors (status code 200)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['open_edit_modal'])
        self.assertFormError(response.context['edit_form'], 'gravida', 'Ensure this value is greater than or equal to 0.')

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class SignupRestrictionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.signup_url = reverse('users:signup')
        
        # Create non-superuser
        self.normal_user = User.objects.create_user(
            id_number='12345678',
            password='testpassword123',
            first_name='John',
            last_name='Doe',
            phone='1234567890',
            role='Doctor'
        )
        
        # Create superuser
        self.superuser = User.objects.create_superuser(
            id_number='87654321',
            password='adminpassword123',
            first_name='Admin',
            last_name='User',
            phone='0987654321',
            role='Admin'
        )

    def test_anonymous_user_redirected_to_login(self):
        """Test that unauthenticated users are redirected to the login page."""
        response = self.client.get(self.signup_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('users:login'), response.url)

    def test_non_superuser_gets_forbidden(self):
        """Test that logged-in non-superusers cannot access the signup page."""
        self.client.login(username='12345678', password='testpassword123')
        response = self.client.get(self.signup_url)
        self.assertEqual(response.status_code, 403)

    def test_superuser_can_access_signup_page(self):
        """Test that superusers can access the signup page."""
        self.client.login(username='87654321', password='adminpassword123')
        response = self.client.get(self.signup_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'users/signup.html')

    def test_superuser_can_create_user_and_remains_logged_in(self):
        """Test that a superuser can register a user, is not logged out, and redirects to signup."""
        self.client.login(username='87654321', password='adminpassword123')
        
        post_data = {
            'first_name': 'Jane',
            'last_name': 'Smith',
            'id_number': '11223344',
            'phone': '0712345678',
            'role': 'Nurse',
            'password': 'newuserpass123',
            'confirm_password': 'newuserpass123'
        }
        
        response = self.client.post(self.signup_url, data=post_data)
        
        # Assert redirect to signup page
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.signup_url)
        
        # Verify user was created in database
        self.assertTrue(User.objects.filter(id_number='11223344').exists())
        new_user = User.objects.get(id_number='11223344')
        self.assertEqual(new_user.role, 'Nurse')
        self.assertTrue(new_user.is_staff)
        
        # Verify the superuser is still logged in
        response_dashboard = self.client.get(reverse('users:dashboard'))
        self.assertEqual(response_dashboard.status_code, 200)

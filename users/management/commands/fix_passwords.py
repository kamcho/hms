from django.core.management.base import BaseCommand
from users.models import User
from django.contrib.auth.hashers import is_password_usable, make_password

class Command(BaseCommand):
    help = 'Hashes plain text passwords for users in the database.'

    def handle(self, *args, **options):
        users = User.objects.all()
        count = 0
        
        for user in users:
            # Django's is_password_usable returns false if passwords start with '!' 
            # or aren't in the expected hash format.
            # But we'll use a more direct check for pbkdf2 prefix which is the default.
            
            is_hashed = (user.password.startswith('pbkdf2_') or 
                         user.password.startswith('argon2') or 
                         user.password.startswith('bcrypt'))
            
            if not is_hashed:
                original_pwd = user.password
                user.set_password(original_pwd)
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Successfully hashed password for user: {user.id_number}'))
                count += 1
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('No plain text passwords found.'))
        else:
            self.stdout.write(self.style.SUCCESS(f'Repair complete. Total hashed: {count}'))

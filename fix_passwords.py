from users.models import User
users = User.objects.all()
count = 0
for u in users:
    is_hashed = (u.password.startswith('pbkdf2_') or 
                 u.password.startswith('argon2') or 
                 u.password.startswith('bcrypt'))
    if not is_hashed:
        u.set_password(u.password)
        u.save()
        print(f"Hashed password for: {u.id_number}")
        count += 1
print(f"Successfully fixed {count} users.")
exit()

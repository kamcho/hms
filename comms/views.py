from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from users.models import User

@login_required
def call_center(request):
    # Fetch all active users to display in the call center
    users = User.objects.filter(is_active=True).order_by('first_name', 'last_name')
    return render(request, 'comms/call_center.html', {'users': users})

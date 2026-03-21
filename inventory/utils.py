from django.utils import timezone
from datetime import time

def get_current_dispensing_department():
    """
    Returns the appropriate department name based on current time:
    Pharmacy (8 AM - 5 PM)
    Mini Pharmacy (5 PM - 8 AM)
    """
    now = timezone.localtime(timezone.now()).time()
    start_time = time(8, 0)
    end_time = time(17, 0)
    
    if start_time <= now < end_time:
        return "Pharmacy"
    else:
        return "Mini Pharmacy"

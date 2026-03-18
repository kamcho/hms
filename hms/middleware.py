import datetime
from django.http import HttpResponse

class LicenseVerificationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set the deadline: 7 days from March 18 is March 25
        deadline = datetime.date(2026, 3, 22)
        
        # Check if the system date is past the deadline
        if datetime.date.today() > deadline:
            # Temporarily disabled bypass for testing
            # if request.user.is_authenticated and request.user.is_superuser:
            #     return self.get_response(request)
                
            return HttpResponse(
                """
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>System Inactive | HMS</title>
                    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@500;800&display=swap" rel="stylesheet">
                </head>
                <body style="margin: 0; background: #0f172a; display: flex; align-items: center; justify-content: center; height: 100vh; font-family: 'Outfit', sans-serif;">
                    <div style="background: #1e293b; border: 1px solid rgba(255,255,255,0.05); padding: 50px; border-radius: 32px; text-align: center; max-width: 480px; box-shadow: 0 40px 120px -20px rgba(0,0,0,0.6);">
                        <div style="background: linear-gradient(135deg, #6366f1 0%, #a855f7 100%); width: 80px; height: 80px; border-radius: 20px; display: flex; align-items: center; justify-content: center; margin: 0 auto 30px auto; color: white; font-size: 2rem;">
                             <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
                        </div>
                        <h1 style="color: white; margin-bottom: 12px; font-weight: 800; font-size: 2.25rem;">System Inactive</h1>
                        <p style="color: #94a3b8; line-height: 1.6; margin-bottom: 25px;">The license for this deployment has expired. To restore full access to your clinical and administrative records, please </p>
                        <p style="color: #6366f1; font-weight: 700; font-size: 0.9rem; text-transform: uppercase; letter-spacing: 1px;">Contact Support or Sales to Renew</p>
                    </div>
                </body>
                </html>
                """,
                status=402 # Payment Required
            )
            
        return self.get_response(request)

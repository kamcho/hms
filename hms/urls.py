"""
URL configuration for hms project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('users/', include(('users.urls', 'users'), namespace='users')),  # Added namespace
    path('home/', include(('home.urls', 'home'), namespace='home')),  # Added namespace
    path('morgue/', include(('morgue.urls', 'morgue'), namespace='morgue')),  # Morgue app
    path('inventory/', include(('inventory.urls', 'inventory'), namespace='inventory')),  # Inventory app
    path('inpatient/', include(('inpatient.urls', 'inpatient'), namespace='inpatient')),  # Inpatient app
    path('', RedirectView.as_view(url='/users/dashboard/', permanent=False)),  # Redirect root to dashboard
    path('lab/', include(('lab.urls', 'lab'), namespace='lab')),   # Lab app
    path('maternity/', include(('maternity.urls', 'maternity'), namespace='maternity')),  # Maternity app
    # Add login/logout URLs for the browsable API
    # path('api-auth/', include('rest_framework.urls')),
    path('accounts/', include(('accounts.urls', 'accounts'), namespace='accounts')),  # Accounts app
    path('comms/', include(('comms.urls', 'comms'), namespace='comms')),  # Comms app
]

# Serve static and media files during development
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Error handlers
handler404 = 'users.views.handler404'
handler500 = 'users.views.handler500'

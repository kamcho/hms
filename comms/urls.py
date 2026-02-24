from django.urls import path
from . import views

app_name = 'comms'

urlpatterns = [
    path('call-center/', views.call_center, name='call_center'),
]

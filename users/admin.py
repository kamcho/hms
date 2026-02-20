from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('id_number', 'first_name', 'last_name', 'phone', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('id_number', 'first_name', 'last_name', 'phone')
    ordering = ('id_number',)
    
    fieldsets = (
        (None, {'fields': ('id_number', 'password')}),
        (_('Personal info'), {'fields': ('first_name', 'last_name', 'phone')}),
        (_('Access'), {'fields': ('role', 'is_active')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('id_number', 'first_name', 'last_name', 'phone', 'role', 'is_active', 'password1', 'password2'),
        }),
    )

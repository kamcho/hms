from .permissions import can_access_hr, get_hr_context


def hr_permissions(request):
    if not request.user.is_authenticated or not can_access_hr(request.user):
        return {}
    return {'hr_ctx': get_hr_context(request.user)}

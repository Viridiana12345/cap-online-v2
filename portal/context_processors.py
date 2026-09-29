from .permissions import is_doctor, is_patient, is_admin


def portal_roles(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {"role_is_doctor": False, "role_is_patient": False, "role_is_admin": False}
    return {
        "role_is_doctor": is_doctor(user),
        "role_is_patient": is_patient(user),
        "role_is_admin": is_admin(user),
    }

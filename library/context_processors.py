from .models import User


def current_library_user(request):
    user_id = request.session.get('library_user_id')

    if not user_id:
        return {
            'current_library_user': None
        }

    user = User.objects.filter(id=user_id).first()

    return {
        'current_library_user': user
    }
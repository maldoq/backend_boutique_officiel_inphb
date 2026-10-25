from rest_framework.permissions import AllowAny
from rest_framework.views import APIView


class PublicAPIView(APIView):
    """Vue publique (site web et mobile) : aucune authentification, accès explicite AllowAny (C.2)."""

    authentication_classes = []
    permission_classes = [AllowAny]

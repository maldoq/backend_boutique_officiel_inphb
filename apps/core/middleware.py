VISITOR_RESPONSE_HEADER = "X-Visitor-Id"


class VisitorHeaderMiddleware:
    """Recopie dans la réponse l'identifiant de visite attribué pendant la requête (get_visitor_id)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        visitor_id = getattr(request, "visitor_id", None)
        if visitor_id and VISITOR_RESPONSE_HEADER not in response:
            response[VISITOR_RESPONSE_HEADER] = visitor_id
        return response

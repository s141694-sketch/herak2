from rest_framework.negotiation import DefaultContentNegotiation


class IgnoreClientContentNegotiation(DefaultContentNegotiation):
    """Always answers with the first renderer; used by endpoints probed by browsers and load balancers."""

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type

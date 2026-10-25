from django.dispatch import receiver

from apps.core.signals import sensitive_change

from .services import log_action


@receiver(sensitive_change, dispatch_uid="audit.log_sensitive_change")
def log_sensitive_change(sender, *, actor, action, obj, changes, request, **kwargs):
    """Journalise les opérations sensibles signalées par core et accounts."""
    log_action(actor=actor, action=action, obj=obj, changes=changes, request=request)

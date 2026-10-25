"""Signaux transverses.

`sensitive_change` permet aux applications situées AVANT `audit` dans l'ordre des dépendances
(core, accounts) de signaler une opération sensible sans importer `audit` (C.2) ; l'application
`audit` s'y abonne et écrit l'entrée du journal, dans la même transaction.
Les applications suivantes appellent directement `apps.audit.services.log_action`.

Arguments : actor, action (« domaine.verbe »), obj, changes ({champ: [avant, après]}), request.
"""

from django.dispatch import Signal

sensitive_change = Signal()


def emit_sensitive_change(*, sender, actor, action: str, obj, changes=None, request=None) -> None:
    sensitive_change.send(
        sender=sender, actor=actor, action=action, obj=obj, changes=changes or {}, request=request
    )

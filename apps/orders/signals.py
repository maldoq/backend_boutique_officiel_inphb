"""Signaux des commandes.

`order_created` est émis APRÈS validation de la transaction (on_commit) : les notifications (étape 16)
s'y abonnent sans que `orders` dépende d'elles. Argument : order.
"""

from django.dispatch import Signal

order_created = Signal()

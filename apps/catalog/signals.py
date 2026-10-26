"""Signaux du catalogue.

`initial_stock_requested` : une variante vient d'être créée avec un stock initial. `catalog` précède
`inventory` (C.2) et ne l'importe pas : c'est `inventory` qui s'abonne et crée le mouvement « initial »,
dans la même transaction (toute erreur annule la création de la variante).

Arguments : variant, quantity, user, request.
"""

from django.dispatch import Signal

initial_stock_requested = Signal()

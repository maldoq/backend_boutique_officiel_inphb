"""Point de retrait initial « Boutique INP-HB Centre » (décision D09).

Seuls le code et le nom sont connus : adresse, horaires et téléphone restent vides, à compléter dans
l'administration (aucune donnée réelle de l'INP-HB n'est inventée, règle A.2).
"""

from django.db import migrations

CODE = "BOUTIQUE-CENTRE"
NAME = "Boutique INP-HB Centre"


def create_pickup_point(apps, schema_editor):
    PickupPoint = apps.get_model("orders", "PickupPoint")
    PickupPoint.objects.get_or_create(code=CODE, defaults={"name": NAME, "is_active": True, "position": 0})


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_pickup_point, migrations.RunPython.noop),
    ]

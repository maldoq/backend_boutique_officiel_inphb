from django.core.exceptions import ValidationError
from django.db.models.signals import m2m_changed, post_delete
from django.dispatch import receiver

from .models import Category, Product, ProductImage, delete_files_on_commit


@receiver(post_delete, sender=ProductImage, dispatch_uid="catalog.product_image_deleted")
def product_image_deleted(sender, instance: ProductImage, **kwargs):
    """Fichiers supprimés du disque et nouvelle image principale désignée si besoin."""
    delete_files_on_commit(
        (instance.image.storage, instance.image.name),
        (instance.thumbnail.storage, instance.thumbnail.name),
    )
    if instance.is_main:
        remaining = ProductImage.objects.filter(product_id=instance.product_id).order_by("position", "id")
        successor = remaining.first()
        if successor is not None:
            remaining.filter(pk=successor.pk).update(is_main=True)


@receiver(post_delete, sender=Category, dispatch_uid="catalog.category_deleted")
def category_deleted(sender, instance: Category, **kwargs):
    if instance.image:
        delete_files_on_commit((instance.image.storage, instance.image.name))


@receiver(m2m_changed, sender=Product.related_products.through, dispatch_uid="catalog.related_not_self")
def forbid_self_relation(sender, instance, action, pk_set, **kwargs):
    if action == "pre_add" and pk_set and instance.pk in pk_set:
        raise ValidationError("Un produit ne peut pas être associé à lui-même.")

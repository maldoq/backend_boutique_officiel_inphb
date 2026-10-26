import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.text import slugify

from apps.core.images import make_thumbnail, reencode_image, validate_uploaded_image
from apps.core.models import SiteSettings, TimeStampedModel
from apps.core.slugs import unique_slug
from apps.core.text import normalize_search

from .choices import AVAILABILITY_RANK, Availability

# Références et SKU : majuscules, chiffres, tirets (ex. INP-TEX-001, INP-TEX-001-M-VERT).
CODE_VALIDATOR = RegexValidator(
    r"^[A-Z0-9][A-Z0-9._-]*$",
    "Utilisez uniquement des majuscules, chiffres, points, tirets ou soulignés.",
)
STANDARD_LABEL = "Standard"


def normalize_code(value: str) -> str:
    """« inp tex 001 » -> « INP-TEX-001 »."""
    return "-".join((value or "").split()).upper()


def normalize_option(value: str) -> str:
    """Espaces superflus retirés : « Vert  » -> « Vert »."""
    return " ".join((value or "").split())


def _upload_path(folder: str, extension: str) -> str:
    return f"{folder}/{timezone.now():%Y/%m}/{uuid.uuid4().hex}{extension}"


def category_image_path(instance, filename: str) -> str:
    return _upload_path("categories", Path(filename).suffix.lower() or ".jpg")


def product_image_path(instance, filename: str) -> str:
    # Nom aléatoire : ni collision, ni information révélée par le nom d'origine.
    return _upload_path("products", Path(filename).suffix.lower() or ".jpg")


def product_thumbnail_path(instance, filename: str) -> str:
    return _upload_path("products/thumbs", ".webp")


def delete_files_on_commit(*names_and_storages) -> None:
    """Supprime des fichiers du stockage une fois la transaction validée (jamais en cas d'annulation)."""
    targets = [(storage, name) for storage, name in names_and_storages if name]
    if targets:
        transaction.on_commit(lambda: [storage.delete(name) for storage, name in targets])


class Category(TimeStampedModel):
    """Catégorie ou sous-catégorie (un seul niveau) du catalogue."""

    name = models.CharField("nom", max_length=120)
    slug = models.SlugField("slug", max_length=140, unique=True, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="catégorie parente",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    description = models.TextField("description", blank=True)
    image = models.ImageField(
        "image",
        upload_to=category_image_path,
        null=True,
        blank=True,
        validators=[validate_uploaded_image],
    )
    position = models.PositiveSmallIntegerField("position", default=0)
    is_active = models.BooleanField("active", default=True)

    class Meta:
        verbose_name = "catégorie"
        verbose_name_plural = "catégories"
        ordering = ["position", "name"]

    def __str__(self):
        return f"{self.parent} › {self.name}" if self.parent_id else self.name

    def save(self, *args, **kwargs):
        self.validate_hierarchy()
        self.slug = slugify(self.slug) if self.slug else unique_slug(self, self.name)
        if self.image and not self.image._committed:
            processed = reencode_image(self.image.file)
            self.image.save(processed.content.name, processed.content, save=False)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        self.validate_hierarchy()

    def validate_hierarchy(self) -> None:
        """Un seul niveau de sous-catégorie, jamais sa propre parente."""
        if not self.parent_id:
            return
        if self.pk is not None and self.parent_id == self.pk:
            raise ValidationError({"parent": "Une catégorie ne peut pas être sa propre parente."})
        if self.parent.parent_id:
            raise ValidationError({"parent": "Un seul niveau de sous-catégorie est autorisé."})
        if self.pk is not None and self.children.exists():
            raise ValidationError(
                {"parent": "Cette catégorie a des sous-catégories : elle ne peut pas en devenir une."}
            )


class Product(TimeStampedModel):
    """Produit vendu ; toujours au moins une variante (« Standard » sans option)."""

    reference = models.CharField(
        "référence", max_length=40, unique=True, validators=[CODE_VALIDATOR], help_text="Ex. INP-TEX-001"
    )
    name = models.CharField("nom", max_length=160)
    slug = models.SlugField(
        "slug",
        max_length=180,
        unique=True,
        blank=True,
        help_text="Généré depuis le nom à la création, puis stable (liens et QR déjà diffusés).",
    )
    category = models.ForeignKey(
        Category, verbose_name="catégorie", on_delete=models.PROTECT, related_name="products"
    )
    short_description = models.CharField("description courte", max_length=255, blank=True)
    description = models.TextField("description", blank=True)
    price_xof = models.PositiveIntegerField("prix (XOF)", validators=[MinValueValidator(1)])
    compare_at_price_xof = models.PositiveIntegerField(
        "prix barré (XOF)", null=True, blank=True, help_text="Doit être supérieur au prix."
    )
    is_active = models.BooleanField("actif", default=True)
    is_featured = models.BooleanField("mis en avant", default=False)
    is_coming_soon = models.BooleanField("bientôt disponible", default=False)
    related_products = models.ManyToManyField(
        "self", verbose_name="produits associés", symmetrical=False, blank=True, related_name="+"
    )
    seo_title = models.CharField("titre SEO", max_length=70, blank=True)
    seo_description = models.CharField("description SEO", max_length=160, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="créé par",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    # Nom, référence, description courte et SKU sans accents ni majuscules : « cle usb » trouve « Clé USB ».
    search_text = models.TextField("texte de recherche", blank=True, editable=False)

    class Meta:
        verbose_name = "produit"
        verbose_name_plural = "produits"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(price_xof__gt=0), name="catalog_product_price_positive"),
            models.CheckConstraint(
                condition=Q(compare_at_price_xof__isnull=True) | Q(compare_at_price_xof__gt=F("price_xof")),
                name="catalog_product_compare_at_gt_price",
                violation_error_message="Le prix barré doit être supérieur au prix.",
            ),
        ]
        indexes = [models.Index(fields=["is_active", "is_featured"], name="catalog_product_listing_idx")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.reference = normalize_code(self.reference)
        self.slug = slugify(self.slug) if self.slug else unique_slug(self, self.name)
        self.search_text = self.build_search_text()
        super().save(*args, **kwargs)

    def build_search_text(self) -> str:
        skus = list(self.variants.values_list("sku", flat=True)) if self.pk else []
        return normalize_search(" ".join([self.name, self.reference, self.short_description, *skus]))

    def refresh_search_text(self) -> None:
        """Après ajout ou modification d'une variante (son SKU est cherchable)."""
        Product.objects.filter(pk=self.pk).update(search_text=self.build_search_text())

    def clean_fields(self, exclude=None):
        # Normalisation AVANT les validateurs de champ (« inp-tex-001 » est accepté et corrigé).
        self.reference = normalize_code(self.reference)
        super().clean_fields(exclude=exclude)

    def clean(self):
        super().clean()
        if (
            self.compare_at_price_xof is not None
            and self.price_xof
            and self.compare_at_price_xof <= self.price_xof
        ):
            raise ValidationError({"compare_at_price_xof": "Le prix barré doit être supérieur au prix."})

    # --- Calculs (utilisent les relations préchargées quand elles le sont) ---

    @property
    def active_variants(self) -> list["ProductVariant"]:
        variants = [variant for variant in self.variants.all() if variant.is_active]
        if variants:
            default = SiteSettings.load().default_low_stock_threshold  # une seule lecture pour toutes
            for variant in variants:
                variant.prime_default_threshold(default)
        return variants

    @property
    def availability(self) -> str:
        """Bientôt disponible, sinon meilleure disponibilité des variantes actives (aucune = rupture)."""
        if self.is_coming_soon:
            return Availability.COMING_SOON
        ranked = [variant.availability for variant in self.active_variants]
        return min(ranked, key=AVAILABILITY_RANK.__getitem__, default=Availability.OUT_OF_STOCK)

    @property
    def availability_label(self) -> str:
        return Availability(self.availability).label

    @property
    def main_image(self) -> "ProductImage | None":
        images = list(self.images.all())
        return next((image for image in images if image.is_main), images[0] if images else None)

    @property
    def min_price_xof(self) -> int:
        """Prix le plus bas réellement payé parmi les variantes actives."""
        return min((variant.effective_price_xof for variant in self.active_variants), default=self.price_xof)

    @property
    def is_on_sale(self) -> bool:
        return self.compare_at_price_xof is not None and self.compare_at_price_xof > self.min_price_xof


class ProductImage(TimeStampedModel):
    """Photo ré-encodée (sans EXIF) + miniature WebP 400 px générée à l'enregistrement."""

    product = models.ForeignKey(
        Product, verbose_name="produit", on_delete=models.CASCADE, related_name="images"
    )
    image = models.ImageField("image", upload_to=product_image_path, validators=[validate_uploaded_image])
    thumbnail = models.ImageField("miniature", upload_to=product_thumbnail_path, blank=True, editable=False)
    width = models.PositiveIntegerField("largeur", default=0, editable=False)
    height = models.PositiveIntegerField("hauteur", default=0, editable=False)
    alt_text = models.CharField("texte alternatif", max_length=160, blank=True)
    position = models.PositiveSmallIntegerField("position", default=0)
    is_main = models.BooleanField("image principale", default=False)

    class Meta:
        verbose_name = "image produit"
        verbose_name_plural = "images produit"
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["product"],
                condition=Q(is_main=True),
                name="catalog_productimage_one_main",
                violation_error_message="Un produit n'a qu'une image principale.",
            ),
        ]

    def __str__(self):
        return self.alt_text or f"Image de {self.product}"

    def get_constraints(self):
        # « Une seule image principale » n'est pas une erreur de saisie : désigner une nouvelle
        # principale retire l'ancienne à l'enregistrement. La contrainte reste garantie en base.
        return [
            (model, [c for c in constraints if c.name != "catalog_productimage_one_main"])
            for model, constraints in super().get_constraints()
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.image and not self.image._committed:
                self._process_upload()
            siblings = ProductImage.objects.filter(product_id=self.product_id).exclude(pk=self.pk)
            if self.is_main:
                siblings.filter(is_main=True).update(
                    is_main=False
                )  # la nouvelle principale remplace l'ancienne
            elif not siblings.filter(is_main=True).exists():
                self.is_main = True  # toujours une image principale
            super().save(*args, **kwargs)

    def _process_upload(self) -> None:
        if self.pk is not None:
            previous = ProductImage.objects.filter(pk=self.pk).values_list("image", "thumbnail").first()
            if previous:
                delete_files_on_commit(*((self.image.storage, name) for name in previous))
        processed = reencode_image(self.image.file)
        self.image.save(processed.content.name, processed.content, save=False)
        self.thumbnail.save("miniature.webp", make_thumbnail(processed.content), save=False)
        self.width, self.height = processed.width, processed.height


class ProductVariant(TimeStampedModel):
    """Déclinaison commandable (taille, couleur, modèle). Porte le stock."""

    product = models.ForeignKey(
        Product, verbose_name="produit", on_delete=models.CASCADE, related_name="variants"
    )
    # null=True côté formulaire uniquement (vide = « à générer », sans faux doublon entre lignes vides) ;
    # la contrainte catalog_variant_sku_required garantit qu'il est toujours renseigné en base.
    sku = models.CharField(
        "SKU",
        max_length=60,
        unique=True,
        null=True,
        blank=True,
        validators=[CODE_VALIDATOR],
        help_text="Généré depuis la référence et les options s'il est laissé vide.",
    )
    size = models.CharField("taille", max_length=40, blank=True)
    color = models.CharField("couleur", max_length=40, blank=True)
    model = models.CharField("modèle", max_length=40, blank=True)
    label = models.CharField("libellé", max_length=120, editable=False)
    price_xof = models.PositiveIntegerField(
        "prix spécifique (XOF)",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Vide : prix du produit.",
    )
    # Modifié uniquement par les services de stock (apps.inventory) : jamais négatif.
    stock_quantity = models.PositiveIntegerField("stock", default=0)
    low_stock_threshold = models.PositiveSmallIntegerField(
        "seuil de stock faible", null=True, blank=True, help_text="Vide : seuil par défaut de la boutique."
    )
    is_active = models.BooleanField("active", default=True)
    position = models.PositiveSmallIntegerField("position", default=0)

    class Meta:
        verbose_name = "variante"
        verbose_name_plural = "variantes"
        ordering = ["position", "id"]
        constraints = [
            # Combinaison unique, sans tenir compte des majuscules (« M » = « m »).
            models.UniqueConstraint(
                F("product"),
                Lower("size"),
                Lower("color"),
                Lower("model"),
                name="catalog_variant_unique_options",
                violation_error_message="Cette combinaison taille / couleur / modèle existe déjà.",
            ),
            models.CheckConstraint(
                condition=Q(stock_quantity__gte=0), name="catalog_variant_stock_non_negative"
            ),
            models.CheckConstraint(
                condition=Q(sku__isnull=False) & ~Q(sku=""), name="catalog_variant_sku_required"
            ),
            models.CheckConstraint(
                condition=Q(price_xof__isnull=True) | Q(price_xof__gt=0),
                name="catalog_variant_price_positive",
            ),
        ]

    _default_threshold: int | None = None

    def __str__(self):
        return f"{self.product} – {self.label}" if self.product_id else self.label

    def save(self, *args, **kwargs):
        self.size, self.color, self.model = map(normalize_option, (self.size, self.color, self.model))
        self.label = self.compute_label()
        self.sku = normalize_code(self.sku) if self.sku else self._generate_sku()
        super().save(*args, **kwargs)
        self.product.refresh_search_text()

    def clean_fields(self, exclude=None):
        # Normalisation AVANT les validateurs de champ et le contrôle d'unicité des options.
        self.size, self.color, self.model = map(normalize_option, (self.size, self.color, self.model))
        self.sku = normalize_code(self.sku) or None
        if self.sku is None and self._product_reference():
            self.sku = self._generate_sku()  # généré dès la validation (contraintes vérifiées ensuite)
        super().clean_fields(exclude=exclude)

    def _product_reference(self) -> str:
        try:
            return self.product.reference or ""
        except Product.DoesNotExist:
            return ""

    def compute_label(self) -> str:
        options = [value for value in (self.size, self.color, self.model) if value]
        return " / ".join(options) or STANDARD_LABEL

    def _generate_sku(self) -> str:
        parts = [self.product.reference, *(slugify(v) for v in (self.size, self.color, self.model) if v)]
        base = normalize_code("-".join(parts))[:60]
        candidate, counter = base, 2
        others = ProductVariant.objects.exclude(pk=self.pk)
        while others.filter(sku=candidate).exists():
            suffix = f"-{counter}"
            candidate, counter = f"{base[: 60 - len(suffix)]}{suffix}", counter + 1
        return candidate

    # --- Calculs ---

    def prime_default_threshold(self, value: int) -> None:
        """Fournit le seuil par défaut déjà lu (évite une requête SiteSettings par variante)."""
        self._default_threshold = value

    @property
    def effective_price_xof(self) -> int:
        return self.price_xof if self.price_xof is not None else self.product.price_xof

    @property
    def threshold(self) -> int:
        if self.low_stock_threshold is not None:
            return self.low_stock_threshold
        if self._default_threshold is None:
            self._default_threshold = SiteSettings.load().default_low_stock_threshold
        return self._default_threshold

    @property
    def availability(self) -> str:
        if self.product.is_coming_soon:
            return Availability.COMING_SOON
        if self.stock_quantity <= 0:
            return Availability.OUT_OF_STOCK
        if self.stock_quantity <= self.threshold:
            return Availability.LOW_STOCK
        return Availability.IN_STOCK

    @property
    def availability_label(self) -> str:
        return Availability(self.availability).label

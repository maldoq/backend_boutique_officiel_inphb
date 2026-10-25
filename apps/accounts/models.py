from django.contrib.auth.models import AbstractUser
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.db import models

from apps.core.models import TimeStampedModel


class UserManager(DjangoUserManager):
    """Gestionnaire sans username : l'e-mail (en minuscules) sert d'identifiant."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("L'adresse e-mail est obligatoire.")
        user = self.model(email=self.normalize_email(email).lower(), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Un superutilisateur doit avoir is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Un superutilisateur doit avoir is_superuser=True.")
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Connexion insensible à la casse de l'e-mail.
        return self.get(**{f"{self.model.USERNAME_FIELD}__iexact": username})


class User(TimeStampedModel, AbstractUser):
    """Utilisateur (personnel au MVP, clients en Phase 2). Connexion par e-mail (E.2)."""

    username = None
    email = models.EmailField("adresse e-mail", unique=True)
    first_name = models.CharField("prénom", max_length=80, blank=True)
    last_name = models.CharField("nom", max_length=80, blank=True)
    phone = models.CharField("téléphone", max_length=20, blank=True)  # normalisé E.164 (étape 2)
    must_change_password = models.BooleanField("doit changer son mot de passe", default=False)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name"]  # obligatoires pour le personnel

    objects = UserManager()

    class Meta:
        verbose_name = "utilisateur"
        verbose_name_plural = "utilisateurs"
        ordering = ["email"]

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

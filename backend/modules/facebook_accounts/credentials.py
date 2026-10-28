from django.db import models
class FacebookCookieSecret(models.Model):
    account = models.OneToOneField(
        "facebook_accounts.FacebookAccount",
        on_delete=models.CASCADE,
        related_name="cookie_secret",
        primary_key=True,
    )
    ciphertext = models.TextField()
    key_version = models.PositiveSmallIntegerField(
        default=1,
    )
    cookie_count = models.PositiveSmallIntegerField(
        default=0,
    )
    updated_at = models.DateTimeField(
        auto_now=True,
    )
    class Meta:
        db_table = "publisher_facebook_cookie_secrets"

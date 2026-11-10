from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0017_product_quality_band_limits'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='gitlab_user_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
    ]

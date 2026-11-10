from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('organizations', '0016_organization_gitlab_group_id_repositoryaccess'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='gitlab_user_id',
            field=models.BigIntegerField(blank=True, null=True, unique=True),
        ),
    ]

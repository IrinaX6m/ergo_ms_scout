from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0014_retention_cleanup')]

    operations = [
        migrations.AddField(
            model_name='proxyprofilerevision',
            name='auth_type',
            field=models.CharField(
                choices=[('basic', 'Basic'), ('none', 'Без авторизации')], default='basic', max_length=5,
            ),
        ),
    ]

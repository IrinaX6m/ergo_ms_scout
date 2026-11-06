from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0007_visualsnapshot')]

    operations = [
        migrations.AddField(
            model_name='run',
            name='dispatch_requested_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

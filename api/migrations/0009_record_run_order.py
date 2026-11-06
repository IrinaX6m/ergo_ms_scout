from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0008_run_dispatch_requested_until')]

    operations = [
        migrations.AddIndex(
            model_name='record',
            index=models.Index(fields=['run', 'created_at', 'id'], name='scout_record_run_order'),
        ),
    ]

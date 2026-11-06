from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0009_record_run_order')]

    operations = [
        migrations.AddField(
            model_name='pagesnapshot',
            name='has_crawl_links',
            field=models.BooleanField(null=True),
        ),
    ]

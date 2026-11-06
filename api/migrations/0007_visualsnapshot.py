import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0006_crawl_frontier')]

    operations = [
        migrations.CreateModel(
            name='VisualSnapshot',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('user_public_id', models.UUIDField()),
                ('source_url', models.CharField(max_length=2000)),
                ('final_url', models.TextField(blank=True, default='')),
                ('status', models.CharField(default='queued', max_length=12)),
                ('body', models.BinaryField(default=bytes)),
                ('charset', models.CharField(blank=True, default='', max_length=40)),
                ('error_code', models.CharField(blank=True, default='', max_length=64)),
                ('error_detail', models.CharField(blank=True, default='', max_length=400)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
            ],
        ),
    ]

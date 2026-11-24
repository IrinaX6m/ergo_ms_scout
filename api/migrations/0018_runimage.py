import uuid

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('scout', '0017_remove_protection_sessions')]

    operations = [
        migrations.CreateModel(
            name='RunImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('source_url', models.TextField()),
                ('url_hash', models.CharField(max_length=64)),
                ('content_type', models.CharField(max_length=40)),
                ('byte_size', models.PositiveIntegerField()),
                ('body', models.BinaryField()),
                ('run', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='scout.run')),
            ],
            options={
                'constraints': [models.UniqueConstraint(fields=('run', 'url_hash'), name='scout_run_image_url')],
            },
        ),
    ]

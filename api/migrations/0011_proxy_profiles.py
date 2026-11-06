import uuid

from django.db import migrations, models
from django.db.models import deletion


class Migration(migrations.Migration):
    dependencies = [('scout', '0010_pagesnapshot_has_crawl_links')]

    operations = [
        migrations.CreateModel(
            name='ProxyProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('user_public_id', models.UUIDField(db_index=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.CreateModel(
            name='ProxyProfileRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('ip', models.GenericIPAddressField()),
                ('port', models.PositiveIntegerField()),
                ('key_id', models.CharField(editable=False, max_length=80)),
                ('ciphertext', models.TextField(blank=True, editable=False)),
                ('profile', models.ForeignKey(on_delete=deletion.CASCADE, related_name='revisions', to='scout.proxyprofile')),
            ],
        ),
        migrations.AddField(
            model_name='jobrevision', name='proxy_profile_revision_public_id',
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='visualsnapshot', name='proxy_profile_revision_public_id',
            field=models.UUIDField(blank=True, null=True),
        ),
    ]

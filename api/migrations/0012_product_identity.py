from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('scout', '0011_proxy_profiles')]

    operations = [
        migrations.AddField(
            model_name='jobrevision', name='identity',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='record', name='entity_key',
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AddField(
            model_name='record', name='observation_index',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='record', name='identity_state',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='evidence', name='observation_index',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='evidence', name='typed_value',
            field=models.JSONField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name='record',
            constraint=models.UniqueConstraint(
                fields=('run', 'entity_key'), condition=models.Q(entity_key__isnull=False),
                name='scout_record_run_entity',
            ),
        ),
        migrations.AddConstraint(
            model_name='evidence',
            constraint=models.UniqueConstraint(
                fields=('record', 'snapshot', 'observation_index', 'field_path', 'locator'),
                condition=models.Q(observation_index__isnull=False), name='scout_evidence_observation',
            ),
        ),
    ]

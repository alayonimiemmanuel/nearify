from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('finder', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='featuredbusiness',
            name='yelp_id',
            field=models.CharField(max_length=255, blank=True, null=True),
        ),
        migrations.AddField(
            model_name='featuredbusiness',
            name='featured_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

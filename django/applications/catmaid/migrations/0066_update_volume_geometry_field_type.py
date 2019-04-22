# Generated by Django 2.1.7 on 2019-03-04 20:52

import catmaid.fields
from django.db import migrations


class Migration(migrations.Migration):
    """The volume geometry field type changed on the Python side. Because the
    underlying database type isn't changed, this migrations doesn't actually
    need to make a database change. It only communicates to Django that the
    field type change is indeed performed.
    """

    dependencies = [
        ('catmaid', '0065_add_extra_nblast_similarity_fields'),
    ]

    operations = [
        migrations.RunSQL(
            migrations.RunSQL.noop,
            migrations.RunSQL.noop,
            [
                migrations.AlterField(
                    model_name='volume',
                    name='geometry',
                    field=catmaid.fields.SerializableGeometryField(),
                ),
            ]),
    ]
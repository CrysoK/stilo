# Generated by Django 5.2.3 on 2025-06-30 03:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_remove_user_is_client'),
    ]

    operations = [
        migrations.AlterField(
            model_name='hairdresser',
            name='address',
            field=models.CharField(max_length=255, verbose_name='Dirección'),
        ),
        migrations.AlterField(
            model_name='hairdresser',
            name='description',
            field=models.TextField(blank=True, verbose_name='Descripción'),
        ),
        migrations.AlterField(
            model_name='hairdresser',
            name='latitude',
            field=models.FloatField(blank=True, null=True, verbose_name='Latitud'),
        ),
        migrations.AlterField(
            model_name='hairdresser',
            name='longitude',
            field=models.FloatField(blank=True, null=True, verbose_name='Longitud'),
        ),
        migrations.AlterField(
            model_name='hairdresser',
            name='name',
            field=models.CharField(max_length=100, verbose_name='Nombre'),
        ),
        migrations.AlterField(
            model_name='hairdresser',
            name='phone_number',
            field=models.CharField(blank=True, max_length=20, verbose_name='Número de teléfono'),
        ),
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(max_length=254, verbose_name='email address'),
        ),
        migrations.AlterField(
            model_name='user',
            name='first_name',
            field=models.CharField(max_length=150, verbose_name='first name'),
        ),
        migrations.AlterField(
            model_name='user',
            name='last_name',
            field=models.CharField(max_length=150, verbose_name='last name'),
        ),
    ]

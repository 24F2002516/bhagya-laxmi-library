from django.db import migrations


def seed_150_seats(apps, schema_editor):
    Seat = apps.get_model("seats", "Seat")
    seats = [
        Seat(
            number=i,
            status="AVAILABLE",
            is_active=True,
            has_power_socket=True,
        )
        for i in range(1, 151)
    ]
    Seat.objects.bulk_create(seats, ignore_conflicts=True)


def unseed_150_seats(apps, schema_editor):
    Seat = apps.get_model("seats", "Seat")
    Seat.objects.filter(number__gte=1, number__lte=150).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("seats", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_150_seats, reverse_code=unseed_150_seats),
    ]

from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Leave
from .utils import generate_and_save_staff_hr_pdfs


@receiver(post_save, sender=Leave)
def on_leave_save(sender, instance, created, **kwargs):
    # If leave becomes fully approved and does not yet have documents, create them.
    if instance.status == "Approved" and instance.documents.count() == 0:
        generate_and_save_staff_hr_pdfs(instance)
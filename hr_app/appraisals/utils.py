from django.urls import reverse
from django.template.loader import get_template
from xhtml2pdf import pisa
from io import BytesIO
from django.core.mail import EmailMessage
from django.conf import settings
from django.contrib.staticfiles import finders
import os


def send_appraisal_email(request, appraisal, subject, recipient_email, file=None):
    link = request.build_absolute_uri(
        reverse('appraisal_detail', args=[appraisal.id])
    )

    message = f"""
    You have an appraisal task.

    Reference: {appraisal.reference}

    You are by this notification requested to complete and submit your appraisal on or before the deadline {appraisal.date_of_submission}.

    Access here:
    {link}
    """

    email = EmailMessage(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [recipient_email],
    )

    # 🔥 Attach uploaded file (NOT saved in DB)
    if file:
        email.attach(file.name, file.read(), file.content_type)

    email.send(fail_silently=False)


def render_to_pdf(template_src, context_dict):
    template = get_template(template_src)
    html = template.render(context_dict)

    result = BytesIO()
    pisa_status = pisa.CreatePDF(html, dest=result,
                                 link_callback=link_callback)

    if not pisa_status.err:
        return result.getvalue()
    return None


def link_callback(uri, rel):
    if uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
    elif uri.startswith(settings.STATIC_URL):
        relative_path = uri.replace(settings.STATIC_URL, "")
        # finders.find() locates the file straight from each app's static/
        # dir (works in dev, where `collectstatic` is rarely run) and falls
        # back to STATIC_ROOT for a deployment that does run collectstatic.
        path = finders.find(relative_path) or os.path.join(settings.STATIC_ROOT, relative_path)
    else:
        return uri

    if not path or not os.path.isfile(path):
        raise Exception(f"Media file not found: {path}")

    return path

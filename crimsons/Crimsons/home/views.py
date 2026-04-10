from django.contrib import messages
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from .forms import ContactForm


def index(request):
    if request.method == "POST":
        form = ContactForm(request.POST)
        if form.is_valid():
            # Hook: send_mail(...) or save to CRM when you are ready.
            messages.success(
                request,
                "Thank you—we have received your message and will get back to you soon.",
            )
            return HttpResponseRedirect(f"{reverse('home')}#contact")
    else:
        form = ContactForm()

    return render(request, "home/index.html", {"form": form})

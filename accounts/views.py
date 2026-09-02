from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
import logging

logger = logging.getLogger(__name__)


def landing(request):
    """Marketing landing page for logged-out visitors."""
    if request.user.is_authenticated:
        return redirect('repositories:list')
    # Pull live aggregate stats from the demo workspace so the CTA
    # section shows real numbers instead of marketing filler.
    from django.db.models import Count, Q
    from analysis.models import Snapshot, CodeEntity, DriftFlag
    entities_documented = (
        CodeEntity.objects
        .filter(generated_docstring__isnull=False)
        .count()
    )
    repositories = Snapshot.objects.values('repository').distinct().count()
    drift_flags = DriftFlag.objects.count()
    return render(request, 'landing.html', {
        'aggregate': {
            'entities_documented': entities_documented,
            'repositories': repositories,
            'drift_flags': drift_flags,
        },
    })


def register_user(request):
    """Register a new user."""
    context = {}

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')

        context['username'] = username
        context['email'] = email

        if not username:
            context['error'] = 'Username is required.'
            return render(request, 'registration/register.html', context)

        if len(username) > 150:
            context['error'] = 'Username must be 150 characters or fewer.'
            return render(request, 'registration/register.html', context)

        if not password:
            context['error'] = 'Password is required.'
            return render(request, 'registration/register.html', context)

        if password != password_confirm:
            context['error'] = 'Passwords do not match.'
            return render(request, 'registration/register.html', context)

        if User.objects.filter(username__iexact=username).exists():
            context['error'] = 'That username is already taken.'
            return render(request, 'registration/register.html', context)

        try:
            validate_password(password)
        except ValidationError as e:
            context['error'] = ' '.join(e.messages)
            return render(request, 'registration/register.html', context)

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )
        except IntegrityError:
            context['error'] = 'That username is already taken.'
            return render(request, 'registration/register.html', context)

        login(request, user)

        return redirect('repositories:list')

    return render(request, 'registration/register.html')

from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth import login
import json
import logging

logger = logging.getLogger(__name__)


def register_user(request):
    """Register a new user."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '')
        password_confirm = request.POST.get('password_confirm', '')
        
        if not username:
            return render(request, 'registration/register.html', {'error': 'Username is required'})
        
        if not password:
            return render(request, 'registration/register.html', {'error': 'Password is required'})
        
        if password != password_confirm:
            return render(request, 'registration/register.html', {'error': 'Passwords do not match'})
        
        if len(password) < 6:
            return render(request, 'registration/register.html', {'error': 'Password must be at least 6 characters'})
        
        if User.objects.filter(username=username).exists():
            return render(request, 'registration/register.html', {'error': 'Username already exists'})
        
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password
        )
        
        login(request, user)
        
        return redirect('repositories:list')
    
    return render(request, 'registration/register.html')

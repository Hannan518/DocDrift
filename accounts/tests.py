import pytest
from django.contrib.auth.models import User
from django.urls import reverse


@pytest.mark.django_db
class TestRegisterView:
    def test_get_renders_form(self, client):
        response = client.get(reverse('register'))
        assert response.status_code == 200

    def test_creates_user_and_logs_in(self, client):
        response = client.post(reverse('register'), {
            'username': 'alice',
            'email': 'alice@example.com',
            'password': 'ValidPass123!',
            'password_confirm': 'ValidPass123!',
        })
        assert response.status_code == 302
        assert User.objects.filter(username='alice').exists()
        # The user is logged in after registration (auto-login).
        assert '_auth_user_id' in client.session

    def test_password_mismatch_keeps_values(self, client):
        response = client.post(reverse('register'), {
            'username': 'bob',
            'email': 'b@e.com',
            'password': 'ValidPass123!',
            'password_confirm': 'different',
        })
        assert response.status_code == 200
        assert b'Passwords do not match' in response.content
        assert not User.objects.filter(username='bob').exists()
        # Repopulated so the user does not retype them
        assert b'value="bob"' in response.content
        assert b'value="b@e.com"' in response.content

    def test_duplicate_username_rejected(self, client):
        User.objects.create_user(username='taken', password='x')
        response = client.post(reverse('register'), {
            'username': 'taken',
            'email': 't@example.com',
            'password': 'ValidPass123!',
            'password_confirm': 'ValidPass123!',
        })
        assert response.status_code == 200
        assert b'already taken' in response.content

    def test_weak_password_rejected(self, client):
        response = client.post(reverse('register'), {
            'username': 'weak',
            'email': '',
            'password': '123',
            'password_confirm': '123',
        })
        assert response.status_code == 200
        assert b'password' in response.content.lower()
        assert not User.objects.filter(username='weak').exists()


@pytest.mark.django_db
class TestLandingView:
    def test_anonymous_sees_landing(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert b'Codebase' in response.content or b'landing' in response.content.lower()

    def test_authenticated_redirects_to_repositories(self, client):
        User.objects.create_user(username='loggedin', password='x')
        client.login(username='loggedin', password='x')
        response = client.get('/')
        assert response.status_code == 302
        assert response.url == reverse('repositories:list')

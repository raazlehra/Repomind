from backend.services import AuthService


def test_login_success():
    svc = AuthService()
    result = svc.login("alice", "pw")
    assert result.get("success") is True

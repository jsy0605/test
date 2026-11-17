"""실제 인증 흐름을 거치는 테스트 전용 관리자 클라이언트."""

TEST_PASSWORD = "Test-only-password42"


def login_admin(client):
    state = client.get("/api/auth/status").json
    if not state["authenticated"]:
        route = "/admin/setup" if state["setup_required"] else "/login"
        response = client.post(route, data={
            "username": "testadmin", "password": TEST_PASSWORD,
            "password_confirm": TEST_PASSWORD, "csrf_token": state["csrf_token"],
        })
        assert response.status_code == 303, response.get_data(as_text=True)
    state = client.get("/api/auth/status").json
    client.environ_base["HTTP_X_CSRF_TOKEN"] = state["csrf_token"]
    return client

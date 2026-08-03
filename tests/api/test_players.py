from typing import Any
from uuid import UUID, uuid4

from fastapi.testclient import TestClient


class TestPlayerCreate:
    """POST /v1/players — регистрация устройства."""

    def test_registration_returns_token_and_zero_xp(self, client: TestClient) -> None:
        response = client.post("/v1/players")

        assert response.status_code == 201
        body = response.json()
        assert UUID(body["player_id"])
        assert body["token"]
        assert body["xp_total"] == 0
        assert body["level"] == 1
        assert body["restored"] is False

    def test_registration_works_without_token(self, client: TestClient) -> None:
        """У ручки нет аутентификации — теста на 401 быть не может по конструкции:
        клиент приходит с пустыми руками, ему нечего предъявить."""
        assert client.post("/v1/players").status_code == 201

    def test_registration_works_without_body(self, client: TestClient) -> None:
        """device_id необязателен: старый клиент его не присылает."""
        assert client.post("/v1/players", json=None).status_code == 201

    def test_without_device_id_each_call_creates_new_player(self, client: TestClient) -> None:
        """Идемпотентности здесь нет намеренно: ключа для неё не существует,
        токен генерирует сервер и показывает один раз."""
        first = client.post("/v1/players").json()
        second = client.post("/v1/players").json()

        assert first["player_id"] != second["player_id"]
        assert first["token"] != second["token"]

    def test_too_long_device_id_rejected(self, client: TestClient) -> None:
        response = client.post("/v1/players", json={"device_id": "x" * 129})

        assert response.status_code == 422


class TestPlayerRegistrationByDevice:
    """POST /v1/players с device_id — восстановление после переустановки."""

    def test_known_device_gets_its_own_record(self, client: TestClient) -> None:
        device_id = f"device-{uuid4()}"
        first = client.post("/v1/players", json={"device_id": device_id}).json()

        second = client.post("/v1/players", json={"device_id": device_id}).json()

        assert second["player_id"] == first["player_id"]
        assert first["restored"] is False
        assert second["restored"] is True

    def test_repeated_registration_issues_new_token(self, client: TestClient) -> None:
        """Старый токен клиент утратил — иначе он бы не регистрировался заново."""
        device_id = f"device-{uuid4()}"
        first = client.post("/v1/players", json={"device_id": device_id}).json()

        second = client.post("/v1/players", json={"device_id": device_id}).json()

        assert second["token"] != first["token"]

    def test_old_token_stops_working(self, client: TestClient) -> None:
        """Ротация отзывает прежний доступ: если старый токен где-то остался,
        он больше не годится."""
        device_id = f"device-{uuid4()}"
        first = client.post("/v1/players", json={"device_id": device_id}).json()
        client.post("/v1/players", json={"device_id": device_id})

        response = client.get(
            "/v1/players/me", headers={"Authorization": f"Bearer {first['token']}"}
        )

        assert response.status_code == 401

    def test_progress_survives_reinstall(self, client: TestClient, make_game_payload: Any) -> None:
        """Ради этого сценария device_id и заводился."""
        device_id = f"device-{uuid4()}"
        first = client.post("/v1/players", json={"device_id": device_id}).json()
        client.post(
            "/v1/games",
            json=make_game_payload(),
            headers={"Authorization": f"Bearer {first['token']}"},
        )

        # Приложение переустановили: токен потерян, device_id прежний.
        restored = client.post("/v1/players", json={"device_id": device_id}).json()

        assert restored["xp_total"] == 100
        assert restored["restored"] is True

    def test_different_devices_get_different_players(self, client: TestClient) -> None:
        first = client.post("/v1/players", json={"device_id": f"device-{uuid4()}"}).json()
        second = client.post("/v1/players", json={"device_id": f"device-{uuid4()}"}).json()

        assert first["player_id"] != second["player_id"]


class TestPlayerRead:
    """GET /v1/players/me."""

    def test_returns_player_state(
        self, client: TestClient, registered_player: dict[str, Any], auth_headers: dict[str, str]
    ) -> None:
        response = client.get("/v1/players/me", headers=auth_headers)

        assert response.status_code == 200
        assert response.json() == {
            "player_id": registered_player["player_id"],
            "xp_total": 0,
            "level": 1,
            "xp_into_level": 0,
            "xp_to_next": 200,
        }

    def test_returns_neither_token_nor_device_id(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Регистрация — единственное место во всём API, где токен виден."""
        body = client.get("/v1/players/me", headers=auth_headers).json()

        assert "token" not in body
        assert "token_hash" not in body
        assert "device_id" not in body

    def test_without_header_returns_401(self, client: TestClient) -> None:
        response = client.get("/v1/players/me")

        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_unknown_token_returns_401(self, client: TestClient) -> None:
        response = client.get(
            "/v1/players/me", headers={"Authorization": "Bearer never-issued-token"}
        )

        assert response.status_code == 401
        # Текст одинаковый для «нет заголовка» и «токен не найден»: подсказывать,
        # существует ли токен, незачем.
        assert response.json()["detail"] == "invalid or missing token"


class TestPlayerUpdate:
    """PATCH /v1/players/me."""

    def test_updates_xp_and_recalculates_level(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch("/v1/players/me", json={"xp_total": 450}, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["xp_total"] == 450
        assert body["level"] == 3
        assert body["xp_into_level"] == 0

    def test_update_visible_on_next_read(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.patch("/v1/players/me", json={"xp_total": 200}, headers=auth_headers)

        assert client.get("/v1/players/me", headers=auth_headers).json()["xp_total"] == 200

    def test_negative_xp_rejected(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.patch("/v1/players/me", json={"xp_total": -1}, headers=auth_headers)

        assert response.status_code == 422

    def test_missing_required_field_returns_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.patch("/v1/players/me", json={}, headers=auth_headers).status_code == 422

    def test_without_token_returns_401(self, client: TestClient) -> None:
        assert client.patch("/v1/players/me", json={"xp_total": 1}).status_code == 401

    def test_does_not_affect_other_player(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        client.patch("/v1/players/me", json={"xp_total": 999}, headers=auth_headers)

        assert client.get("/v1/players/me", headers=other_auth_headers).json()["xp_total"] == 0


class TestPlayerDelete:
    """DELETE /v1/players/me."""

    def test_deletes_player(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        response = client.delete("/v1/players/me", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["games_deleted"] == 0

    def test_token_stops_working_after_deletion(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        client.delete("/v1/players/me", headers=auth_headers)

        assert client.get("/v1/players/me", headers=auth_headers).status_code == 401

    def test_games_removed_by_cascade(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_games: list[dict[str, Any]],
    ) -> None:
        response = client.delete("/v1/players/me", headers=auth_headers)

        assert len(existing_games) == 3
        assert response.json()["games_deleted"] == 3

    def test_without_token_returns_401(self, client: TestClient) -> None:
        assert client.delete("/v1/players/me").status_code == 401

    def test_does_not_affect_other_player(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
    ) -> None:
        client.delete("/v1/players/me", headers=auth_headers)

        assert client.get("/v1/players/me", headers=other_auth_headers).status_code == 200

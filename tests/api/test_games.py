from collections.abc import Callable
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

MakePayload = Callable[..., dict[str, Any]]


class TestGameCreate:
    """POST /v1/games — засчитать победу."""

    def test_win_awards_xp(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        payload = make_game_payload()

        response = client.post("/v1/games", json=payload, headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["client_game_id"] == payload["client_game_id"]
        assert body["xp_awarded"] == 100
        assert body["xp_total"] == 100
        assert body["already_counted"] is False
        assert body["game_id"]

    def test_two_wins_raise_level(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Порог второго уровня — 200 опыта, то есть две эталонные партии."""
        client.post("/v1/games", json=make_game_payload(), headers=auth_headers)
        second = client.post("/v1/games", json=make_game_payload(), headers=auth_headers).json()

        assert second["xp_total"] == 200
        assert second["level"] == 2
        assert second["xp_to_next"] == 250

    def test_retry_does_not_award_xp_twice(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Идемпотентность по (player_id, client_game_id): мобильная сеть
        ретраит запросы, и второй такой же не должен стоить удвоенного опыта."""
        payload = make_game_payload()

        first = client.post("/v1/games", json=payload, headers=auth_headers).json()
        second = client.post("/v1/games", json=payload, headers=auth_headers).json()

        assert first["already_counted"] is False
        assert second["already_counted"] is True
        assert second["game_id"] == first["game_id"]
        assert second["xp_total"] == first["xp_total"] == 100

    def test_same_client_game_id_across_players_is_fine(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
        make_game_payload: MakePayload,
    ) -> None:
        """Ключ идемпотентности составной: уникален в пределах игрока,
        а не глобально. Клиенты генерируют его независимо."""
        payload = make_game_payload()

        first = client.post("/v1/games", json=payload, headers=auth_headers).json()
        second = client.post("/v1/games", json=payload, headers=other_auth_headers).json()

        assert first["already_counted"] is False
        assert second["already_counted"] is False
        assert second["xp_total"] == 100

    def test_without_token_returns_401(
        self, client: TestClient, make_game_payload: MakePayload
    ) -> None:
        assert client.post("/v1/games", json=make_game_payload()).status_code == 401

    def test_zero_duration_rejected(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        response = client.post(
            "/v1/games", json=make_game_payload(duration_ms=0), headers=auth_headers
        )

        assert response.status_code == 422

    def test_huge_duration_rejected_not_crashing(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Граница стоит не ради игрового смысла, а чтобы стозначное число
        не доехало до драйвера и не дало 500 вместо честного 422."""
        response = client.post(
            "/v1/games", json=make_game_payload(duration_ms=10**30), headers=auth_headers
        )

        assert response.status_code == 422

    def test_long_game_still_awards_xp(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Игра делается для человека, который играет неспешно: час раскладывания
        не должен обнулять награду."""
        response = client.post(
            "/v1/games", json=make_game_payload(duration_ms=3_600_000), headers=auth_headers
        )

        assert response.json()["xp_awarded"] == 50

    def test_deal_cards_and_replay_accepted_unvalidated(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Задел на итерацию 2: поля складываются в базу как есть."""
        payload = make_game_payload(
            deal_cards=["nonsense", 42, {"nested": True}], replay={"a": None}
        )

        response = client.post("/v1/games", json=payload, headers=auth_headers)

        assert response.status_code == 200

    def test_unknown_fields_ignored(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Приложение на устройстве нельзя обновить по требованию: поле от более
        новой версии клиента не должно стоить игроку опыта."""
        response = client.post(
            "/v1/games", json=make_game_payload(field_from_future="x"), headers=auth_headers
        )

        assert response.status_code == 200


class TestGameList:
    """GET /v1/games."""

    def test_returns_player_games(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_games: list[dict[str, Any]],
    ) -> None:
        response = client.get("/v1/games", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == len(existing_games) == 3
        assert len(body["items"]) == 3

    def test_empty_list_for_new_player(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        body = client.get("/v1/games", headers=auth_headers).json()

        assert body["total"] == 0
        assert body["items"] == []

    def test_other_players_games_not_visible(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_player_game: dict[str, Any],
    ) -> None:
        body = client.get("/v1/games", headers=auth_headers).json()

        assert body["total"] == 0
        assert other_player_game["game_id"] not in [item["game_id"] for item in body["items"]]

    def test_pagination(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_games: list[dict[str, Any]],
    ) -> None:
        first_page = client.get("/v1/games?limit=2&offset=0", headers=auth_headers).json()
        second_page = client.get("/v1/games?limit=2&offset=2", headers=auth_headers).json()

        assert len(first_page["items"]) == 2
        assert len(second_page["items"]) == 1
        assert first_page["total"] == second_page["total"] == 3
        # Страницы не пересекаются — за это отвечает добор сортировки по id.
        ids = [item["game_id"] for item in first_page["items"] + second_page["items"]]
        assert len(set(ids)) == 3

    def test_too_large_limit_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Без верхней границы один запрос вытянул бы всю историю в память."""
        assert client.get("/v1/games?limit=101", headers=auth_headers).status_code == 422

    def test_negative_offset_rejected(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.get("/v1/games?offset=-1", headers=auth_headers).status_code == 422

    def test_without_token_returns_401(self, client: TestClient) -> None:
        assert client.get("/v1/games").status_code == 401


class TestGameRead:
    """GET /v1/games/{game_id}."""

    def test_returns_full_game(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        response = client.get(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        assert response.status_code == 200
        body = response.json()
        assert body["game_id"] == existing_game["game_id"]
        assert body["duration_ms"] == 300_000
        assert body["xp_awarded"] == 100
        assert body["xp_formula_version"] == 1
        assert body["deal_cards"] == [1, 2, 3]
        assert body["replay"] == {"moves": 4}

    def test_missing_game_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.get(f"/v1/games/{uuid4()}", headers=auth_headers)

        assert response.status_code == 404
        assert response.json()["detail"] == "game not found"

    def test_other_players_game_returns_404_not_403(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_player_game: dict[str, Any],
    ) -> None:
        """403 сообщал бы, что партия существует, — то есть позволял бы
        перебором нащупывать чужие идентификаторы."""
        response = client.get(f"/v1/games/{other_player_game['game_id']}", headers=auth_headers)

        assert response.status_code == 404

    def test_malformed_id_returns_422(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.get("/v1/games/not-a-uuid", headers=auth_headers).status_code == 422

    def test_without_token_returns_401(
        self, client: TestClient, existing_game: dict[str, Any]
    ) -> None:
        assert client.get(f"/v1/games/{existing_game['game_id']}").status_code == 401


class TestGameUpdate:
    """PATCH /v1/games/{game_id}."""

    def test_updates_deal_cards_without_touching_xp(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        response = client.patch(
            f"/v1/games/{existing_game['game_id']}",
            json={"deal_cards": ["updated"]},
            headers=auth_headers,
        )

        assert response.status_code == 200
        assert response.json()["deal_cards"] == ["updated"]
        assert response.json()["xp_awarded"] == 100
        assert client.get("/v1/players/me", headers=auth_headers).json()["xp_total"] == 100

    def test_duration_change_recalculates_xp(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        """8 минут — 63 опыта вместо 100 за эталонные 5."""
        response = client.patch(
            f"/v1/games/{existing_game['game_id']}",
            json={"duration_ms": 480_000},
            headers=auth_headers,
        )

        assert response.json()["xp_awarded"] == 63

    def test_xp_difference_applied_to_player(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        """Иначе в сумме остался бы опыт за длительность, которой больше нет."""
        client.patch(
            f"/v1/games/{existing_game['game_id']}",
            json={"duration_ms": 480_000},
            headers=auth_headers,
        )

        assert client.get("/v1/players/me", headers=auth_headers).json()["xp_total"] == 63

    def test_explicit_null_clears_deal_cards(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        """Отличать «не прислали» от «прислали null» обязательно."""
        response = client.patch(
            f"/v1/games/{existing_game['game_id']}",
            json={"deal_cards": None},
            headers=auth_headers,
        )

        assert response.json()["deal_cards"] is None
        # replay не присылали — он остался нетронутым.
        assert response.json()["replay"] == {"moves": 4}

    def test_empty_body_returns_game_unchanged(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        """UPDATE без SET — синтаксическая ошибка, поэтому пустой запрос
        трактуется как чтение."""
        response = client.patch(
            f"/v1/games/{existing_game['game_id']}", json={}, headers=auth_headers
        )

        assert response.status_code == 200
        assert response.json()["xp_awarded"] == 100

    def test_missing_game_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        response = client.patch(
            f"/v1/games/{uuid4()}", json={"duration_ms": 1000}, headers=auth_headers
        )

        assert response.status_code == 404

    def test_cannot_update_other_players_game(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_player_game: dict[str, Any],
    ) -> None:
        response = client.patch(
            f"/v1/games/{other_player_game['game_id']}",
            json={"duration_ms": 1000},
            headers=auth_headers,
        )

        assert response.status_code == 404

    def test_zero_duration_rejected(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        response = client.patch(
            f"/v1/games/{existing_game['game_id']}",
            json={"duration_ms": 0},
            headers=auth_headers,
        )

        assert response.status_code == 422

    def test_without_token_returns_401(
        self, client: TestClient, existing_game: dict[str, Any]
    ) -> None:
        response = client.patch(f"/v1/games/{existing_game['game_id']}", json={"duration_ms": 1000})

        assert response.status_code == 401


class TestGameDelete:
    """DELETE /v1/games/{game_id}."""

    def test_deletes_game(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        response = client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        assert response.status_code == 200
        assert response.json()["game_id"] == existing_game["game_id"]
        assert response.json()["xp_removed"] == 100

    def test_reclaims_awarded_xp(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        """Иначе в сумме остался бы опыт за партию, которой больше нет."""
        response = client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        assert response.json()["xp_total"] == 0
        assert client.get("/v1/players/me", headers=auth_headers).json()["xp_total"] == 0

    def test_game_not_readable_after_deletion(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        response = client.get(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        assert response.status_code == 404

    def test_repeated_deletion_returns_404(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
    ) -> None:
        client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        response = client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        assert response.status_code == 404

    def test_frees_client_game_id(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        existing_game: dict[str, Any],
        make_game_payload: MakePayload,
    ) -> None:
        """Уникальность составная и живёт в строке: удалили строку —
        тот же client_game_id снова свободен."""
        client.delete(f"/v1/games/{existing_game['game_id']}", headers=auth_headers)

        response = client.post(
            "/v1/games",
            json=make_game_payload(client_game_id=existing_game["client_game_id"]),
            headers=auth_headers,
        )

        assert response.json()["already_counted"] is False

    def test_missing_game_returns_404(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        assert client.delete(f"/v1/games/{uuid4()}", headers=auth_headers).status_code == 404

    def test_cannot_delete_other_players_game(
        self,
        client: TestClient,
        auth_headers: dict[str, str],
        other_auth_headers: dict[str, str],
        other_player_game: dict[str, Any],
    ) -> None:
        response = client.delete(f"/v1/games/{other_player_game['game_id']}", headers=auth_headers)

        assert response.status_code == 404
        # И партия на месте у владельца.
        owner_view = client.get(
            f"/v1/games/{other_player_game['game_id']}", headers=other_auth_headers
        )
        assert owner_view.status_code == 200

    def test_without_token_returns_401(
        self, client: TestClient, existing_game: dict[str, Any]
    ) -> None:
        assert client.delete(f"/v1/games/{existing_game['game_id']}").status_code == 401

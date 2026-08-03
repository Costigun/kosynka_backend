from app.security import generate_token, hash_token


class TestTokenGeneration:
    """Генерация токена устройства."""

    def test_token_is_unique_every_time(self) -> None:
        assert len({generate_token() for _ in range(100)}) == 100

    def test_token_is_long_enough(self) -> None:
        """32 байта энтропии в urlsafe-виде — около 43 символов."""
        assert len(generate_token()) >= 40


class TestTokenHashing:
    """Хеширование токена перед записью в базу."""

    def test_hash_does_not_contain_the_token(self) -> None:
        """Главное свойство: по содержимому колонки token_hash токен
        не восстановить."""
        token = generate_token()

        digest = hash_token(token)

        assert token not in digest
        assert len(digest) == 64
        assert set(digest) <= set("0123456789abcdef")

    def test_hash_is_deterministic(self) -> None:
        """Иначе поиск игрока по токену не работал бы: соли здесь нет намеренно."""
        token = generate_token()

        assert hash_token(token) == hash_token(token)

    def test_different_tokens_give_different_hashes(self) -> None:
        assert hash_token(generate_token()) != hash_token(generate_token())

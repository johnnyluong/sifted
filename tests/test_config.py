import pytest

from sift.config import Settings, check_cron


@pytest.mark.parametrize("cron", ["0 18 * * 0", "0 18 * * 0-4", "0 18 * * */2"])
def test_numeric_weekdays_are_rejected(cron: str) -> None:
    with pytest.raises(ValueError, match="names"):
        check_cron(cron)


def test_named_weekdays_pass() -> None:
    assert check_cron("0 18 * * SUN") == "0 18 * * SUN"
    assert Settings(_env_file=None, digest_cron="0 9 * * mon-fri").digest_cron == "0 9 * * mon-fri"  # pyright: ignore[reportCallIssue]


def test_bad_cron_rejected_at_startup() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, digest_cron="every sunday")  # pyright: ignore[reportCallIssue]


def test_blank_env_values_fall_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEEP_THRESHOLD", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.keep_threshold == 60
    assert s.anthropic_api_key is None


def test_secrets_listed_for_redaction() -> None:
    s = Settings(_env_file=None, anthropic_api_key="sk-ant-secret-value")  # pyright: ignore[reportCallIssue]
    assert s.secrets() == ["sk-ant-secret-value"]

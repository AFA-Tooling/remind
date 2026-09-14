"""Tests for the Gmail send retry/backoff logic.

A batch of reminders sent back-to-back with no delay reliably crosses Gmail's
per-minute sending quota partway through — before this fix, every send after
that point failed outright with no retry, silently dropping that day's
reminder for anyone later in the batch (see the CS61A "Hog" run on 2026-09-14,
20 of 324 sends lost this way).
"""
import gmail_service
from googleapiclient.errors import HttpError


class FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "error"


def make_http_error(status, message):
    return HttpError(FakeResp(status), message.encode())


class FakeMessages:
    """Stands in for service.users().messages() — holds the call count/outcome
    list itself, since a real _send_with_retry calls .send().execute() fresh
    each attempt but service.users().messages() keeps returning the same
    object, so state must live here, not on whatever .send() returns."""

    def __init__(self, outcomes):
        self._outcomes = outcomes
        self.calls = 0

    def send(self, userId, body):
        return self  # .execute() is called on whatever .send() returns

    def execute(self):
        outcome = self._outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeUsers:
    def __init__(self, outcomes):
        self.messages_obj = FakeMessages(outcomes)

    def messages(self):
        return self.messages_obj


class FakeService:
    def __init__(self, outcomes):
        self.users_obj = FakeUsers(outcomes)

    def users(self):
        return self.users_obj


def test_is_rate_limit_error_matches_429():
    e = make_http_error(429, "rate limited")
    assert gmail_service._is_rate_limit_error(e)


def test_is_rate_limit_error_matches_403_rate_limit_exceeded():
    e = make_http_error(403, '"reason": "rateLimitExceeded"')
    assert gmail_service._is_rate_limit_error(e)


def test_is_rate_limit_error_matches_403_quota_exceeded():
    e = make_http_error(403, '"reason": "quotaExceeded"')
    assert gmail_service._is_rate_limit_error(e)


def test_is_rate_limit_error_does_not_match_plain_403():
    # A permission-denied 403 must not be treated as retryable — retrying
    # that forever would just waste 5 attempts on something that can never
    # succeed.
    e = make_http_error(403, '"reason": "forbidden"')
    assert not gmail_service._is_rate_limit_error(e)


def test_send_with_retry_succeeds_first_try(monkeypatch):
    monkeypatch.setattr(gmail_service.time, "sleep", lambda s: None)
    service = FakeService([{"id": "msg1"}])
    result = gmail_service._send_with_retry(service, {"raw": "x"})
    assert result == {"id": "msg1"}
    assert service.users_obj.messages_obj.calls == 1


def test_send_with_retry_recovers_after_rate_limit(monkeypatch):
    slept = []
    monkeypatch.setattr(gmail_service.time, "sleep", lambda s: slept.append(s))
    outcomes = [make_http_error(429, "rate limited"), {"id": "msg1"}]
    service = FakeService(outcomes)
    result = gmail_service._send_with_retry(service, {"raw": "x"})
    assert result == {"id": "msg1"}
    assert len(slept) == 1, "must back off once before the retry that succeeds"


def test_send_with_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(gmail_service.time, "sleep", lambda s: None)
    outcomes = [make_http_error(429, "rate limited")] * 5
    service = FakeService(outcomes)
    raised = None
    try:
        gmail_service._send_with_retry(service, {"raw": "x"}, max_attempts=5)
    except HttpError as e:
        raised = e
    assert raised is not None, "must eventually raise rather than retry forever"
    assert service.users_obj.messages_obj.calls == 5


def test_send_with_retry_does_not_retry_non_rate_limit_error(monkeypatch):
    slept = []
    monkeypatch.setattr(gmail_service.time, "sleep", lambda s: slept.append(s))
    outcomes = [make_http_error(403, '"reason": "forbidden"')]
    service = FakeService(outcomes)
    raised = None
    try:
        gmail_service._send_with_retry(service, {"raw": "x"})
    except HttpError as e:
        raised = e
    assert raised is not None
    assert slept == [], "a non-rate-limit error must fail immediately, not back off"
    assert service.users_obj.messages_obj.calls == 1

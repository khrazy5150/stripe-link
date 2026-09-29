"""Renewing an access token from the refresh token the session already holds.

This closes a gap that was invisible rather than subtle: `session_from_cognito_user` has always returned
`refresh_token` and `expires_in`, and nothing anywhere read either one. Nothing noticed because no authorizer
verifies the access token, so an expired token worked exactly as well as a fresh one. The day one does, an
hour-old dashboard 401s on every screen (plans/API_AUTHENTICATION.md).

The cases worth pinning are the ones a happy-path test would miss: a refresh Cognito REFUSES must answer 401
rather than 400, because the client's only correct reaction is to drop the session and show login; and the
refresh token must survive a response that omits it, since Cognito only returns a new one when rotation is
enabled on the app client -- returning None there would blank the caller's only means of ever refreshing again.
"""
import json
import os
import unittest
from unittest.mock import patch

from handlers.auth import handler as auth_handler


class FakeClientError(Exception):
    """Shaped like botocore's ClientError, which is what is_cognito_client_error sniffs for."""

    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code, "Message": f"{code} from Cognito"}}


class FakeCognito:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    def initiate_auth(self, **kwargs):
        self.calls.append(kwargs)
        if self.raises:
            raise self.raises
        return self.result


def refresh(cognito, body):
    with patch.dict(os.environ, {"COGNITO_USER_POOL_CLIENT_ID": "client-app"}, clear=False):
        return auth_handler(
            {"httpMethod": "POST", "path": "/auth/refresh", "body": json.dumps(body)},
            None,
            cognito=cognito,
            tenant_repository=object(),
            user_repository=object(),
        )


class AuthRefreshTests(unittest.TestCase):
    def test_returns_a_new_access_token(self):
        cognito = FakeCognito({"AuthenticationResult": {
            "AccessToken": "new-access", "IdToken": "new-id", "ExpiresIn": 3600, "TokenType": "Bearer"}})
        response = refresh(cognito, {"refresh_token": "rt-1"})
        self.assertEqual(response["statusCode"], 200)
        session = json.loads(response["body"])["session"]
        self.assertEqual(session["access_token"], "new-access")
        self.assertEqual(session["expires_in"], 3600)
        self.assertTrue(session["refreshed_at"])

    def test_uses_the_refresh_token_auth_flow(self):
        cognito = FakeCognito({"AuthenticationResult": {"AccessToken": "a"}})
        refresh(cognito, {"refresh_token": "rt-1"})
        self.assertEqual(cognito.calls[0]["AuthFlow"], "REFRESH_TOKEN_AUTH")
        self.assertEqual(cognito.calls[0]["AuthParameters"], {"REFRESH_TOKEN": "rt-1"})

    def test_keeps_the_caller_refresh_token_when_cognito_returns_none(self):
        # Cognito returns a NEW refresh token only when rotation is enabled on the app client. Passing its
        # absent value straight through would hand the client None and cost it the ability to refresh again --
        # a session that dies an hour later for no visible reason.
        cognito = FakeCognito({"AuthenticationResult": {"AccessToken": "a", "ExpiresIn": 3600}})
        session = json.loads(refresh(cognito, {"refresh_token": "rt-original"})["body"])["session"]
        self.assertEqual(session["refresh_token"], "rt-original")

    def test_passes_through_a_rotated_refresh_token(self):
        cognito = FakeCognito({"AuthenticationResult": {"AccessToken": "a", "RefreshToken": "rt-rotated"}})
        session = json.loads(refresh(cognito, {"refresh_token": "rt-original"})["body"])["session"]
        self.assertEqual(session["refresh_token"], "rt-rotated")

    def test_a_rejected_refresh_is_401_not_400(self):
        # The status IS the contract here: the client clears the session on 401 and shows a validation error on
        # 400. A revoked or expired refresh token is the former.
        for code in ("NotAuthorizedException", "UserNotFoundException"):
            response = refresh(FakeCognito(raises=FakeClientError(code)), {"refresh_token": "rt-dead"})
            self.assertEqual(response["statusCode"], 401, code)
            self.assertEqual(json.loads(response["body"])["error"], "refresh_rejected", code)

    def test_other_cognito_errors_keep_their_own_status(self):
        response = refresh(FakeCognito(raises=FakeClientError("TooManyRequestsException")), {"refresh_token": "r"})
        self.assertEqual(response["statusCode"], 400)
        self.assertEqual(json.loads(response["body"])["error"], "TooManyRequestsException")

    def test_a_challenge_response_is_a_relogin(self):
        # 200 from Cognito with no token means a challenge (MFA enrolment, forced password change). A silent
        # refresh cannot satisfy one, so it must not be reported as success.
        response = refresh(FakeCognito({"ChallengeName": "MFA_SETUP"}), {"refresh_token": "rt-1"})
        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(json.loads(response["body"])["error"], "refresh_incomplete")

    def test_missing_refresh_token_is_a_validation_error(self):
        response = refresh(FakeCognito({"AuthenticationResult": {"AccessToken": "a"}}), {})
        self.assertEqual(response["statusCode"], 400)

    def test_refresh_never_reads_a_repository(self):
        # The response carries only tokens. The caller does not get to say who it is, and we do not look a user
        # up on its word -- identity comes from the minted token, which is what an authorizer verifies.
        # Passing object() as both repositories means any attribute access would raise.
        cognito = FakeCognito({"AuthenticationResult": {"AccessToken": "a"}})
        session = json.loads(refresh(cognito, {"refresh_token": "rt-1"})["body"])["session"]
        self.assertEqual(
            sorted(session),
            ["access_token", "expires_in", "id_token", "refresh_token", "refreshed_at", "token_type"])


if __name__ == "__main__":
    unittest.main()

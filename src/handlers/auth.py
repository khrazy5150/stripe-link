import os
import time
import uuid
from typing import Any

from stripe_link.common import error_response, json_response, parse_json_body
from stripe_link.domain.documents import (
    DocumentValidationError,
    validate_tenant_profile,
    validate_user_profile,
)
from stripe_link.repositories.documents import (
    RepositoryError,
    tenant_profiles_registration_repositories,
    tenant_profiles_repository,
    user_profiles_repository,
)


def handler(
    event,
    context,
    cognito=None,
    tenant_repository=None,
    tenant_registration_repositories=None,
    user_repository=None,
):
    provided_tenant_repository = tenant_repository is not None
    cognito = cognito or cognito_client()
    tenant_repository = tenant_repository or tenant_profiles_repository()
    if tenant_registration_repositories is None:
        tenant_registration_repositories = (
            [tenant_repository]
            if provided_tenant_repository
            else tenant_profiles_registration_repositories()
        )
    user_repository = user_repository or user_profiles_repository()
    method = (event or {}).get("httpMethod", "").upper()
    path = (event or {}).get("path", "")

    if method == "OPTIONS":
        return json_response({})
    if method != "POST":
        return error_response(f"Unsupported method '{method}'.", status_code=405, code="method_not_allowed")

    try:
        if path.endswith("/auth/register"):
            return register(event, cognito, tenant_registration_repositories, user_repository)
        if path.endswith("/auth/confirm"):
            return confirm(event, cognito, tenant_repository, tenant_registration_repositories, user_repository)
        if path.endswith("/auth/login"):
            return login(event, cognito, tenant_repository, user_repository)
        if path.endswith("/auth/forgot"):
            return forgot_password(event, cognito)
        if path.endswith("/auth/reset"):
            return reset_password(event, cognito)
    except (DocumentValidationError, RepositoryError, ValueError) as exc:
        return error_response(str(exc), code="invalid_auth_request")
    except Exception as exc:
        if not is_cognito_client_error(exc):
            raise
        return cognito_error(exc)

    return error_response("Unknown auth route.", status_code=404, code="not_found")


def register(event, cognito, tenant_repositories, user_repository):
    body = parse_json_body(event)
    email = required(body, "email").lower()
    password = required(body, "password")
    first_name = required(body, "first_name")
    last_name = required(body, "last_name")
    phone_number = str(body.get("phone_number") or "").strip()
    now = epoch()

    attributes = [
        {"Name": "email", "Value": email},
        {"Name": "given_name", "Value": first_name},
        {"Name": "family_name", "Value": last_name},
    ]
    if phone_number:
        attributes.append({"Name": "phone_number", "Value": phone_number})

    result = cognito.sign_up(
        ClientId=user_pool_client_id(),
        Username=email,
        Password=password,
        UserAttributes=attributes,
    )
    user_id = result.get("UserSub") or email
    client_id = client_id_for(body, user_id)

    tenant = {
        "schema_version": "2026-05-29",
        "document_type": "tenant_profile",
        "tenant_id": client_id,
        "owner_email": email,
        "owner": {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "phone_number": phone_number,
            "email_verified": False,
            "phone_verified": False,
            "cognito_username": email,
        },
        "auth": {
            "provider": "cognito",
            "status": "pending_confirmation",
            "confirmed_at": None,
        },
        "billing_status": "trial",
        "tier_id": str(body.get("tier_id") or "basic"),
        "created_at": now,
        "updated_at": now,
    }
    validate_tenant_profile(tenant)
    for tenant_repository in tenant_repositories:
        tenant_repository.put(tenant)

    profile = user_profile_document(
        client_id=client_id,
        user_id=user_id,
        email=email,
        first_name=first_name,
        last_name=last_name,
        status="pending_confirmation",
        now=now,
    )
    validate_user_profile(profile)
    user_repository.put(profile)

    return json_response({
        "message": "Account created. Check your email for the verification code.",
        "client_id": client_id,
        "tenant_id": client_id,
        "user_id": user_id,
        "delivery": delivery(result.get("CodeDeliveryDetails")),
    }, status_code=201)


def confirm(event, cognito, tenant_repository, tenant_repositories, user_repository):
    body = parse_json_body(event)
    email = required(body, "email").lower()
    code = required(body, "code")
    cognito.confirm_sign_up(ClientId=user_pool_client_id(), Username=email, ConfirmationCode=code)

    user = cognito.admin_get_user(UserPoolId=user_pool_id(), Username=email)
    session = session_from_cognito_user(user)
    now = epoch()

    tenant = tenant_repository.get(session["tenant_id"], session["tenant_id"])
    if tenant:
        tenant.setdefault("auth", {})
        tenant["auth"]["provider"] = "cognito"
        tenant["auth"]["status"] = "confirmed"
        tenant["auth"]["confirmed_at"] = now
        tenant["updated_at"] = now
        for target_repository in tenant_repositories:
            target_repository.put(tenant)

    profile = user_repository.get(session["tenant_id"], session["user_id"])
    if profile:
        profile["status"] = "active"
        profile.setdefault("auth", {})
        profile["auth"]["email_verified"] = True
        profile["updated_at"] = now
        user_repository.put(profile)

    return json_response({"message": "Email confirmed. You can sign in now.", "session": session})


def login(event, cognito, tenant_repository, user_repository):
    body = parse_json_body(event)
    email = required(body, "email").lower()
    password = required(body, "password")
    result = cognito.initiate_auth(
        ClientId=user_pool_client_id(),
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": email,
            "PASSWORD": password,
        },
    )
    auth = result.get("AuthenticationResult") or {}
    user = cognito.admin_get_user(UserPoolId=user_pool_id(), Username=email)
    session = session_from_cognito_user(user, auth)

    now = epoch()
    profile = user_repository.get(session["tenant_id"], session["user_id"])
    if profile:
        profile.setdefault("auth", {})
        profile["auth"]["last_login_at"] = now
        profile["updated_at"] = now
        user_repository.put(profile)

    tenant = tenant_repository.get(session["tenant_id"], session["tenant_id"])
    return json_response({"session": session, "tenant": tenant})


def forgot_password(event, cognito):
    body = parse_json_body(event)
    result = cognito.forgot_password(ClientId=user_pool_client_id(), Username=required(body, "email").lower())
    return json_response({
        "message": "Password reset code sent.",
        "delivery": delivery(result.get("CodeDeliveryDetails")),
    })


def reset_password(event, cognito):
    body = parse_json_body(event)
    cognito.confirm_forgot_password(
        ClientId=user_pool_client_id(),
        Username=required(body, "email").lower(),
        ConfirmationCode=required(body, "code"),
        Password=required(body, "new_password"),
    )
    return json_response({"message": "Password updated. You can sign in now."})


def user_profile_document(*, client_id, user_id, email, first_name, last_name, status, now):
    return {
        "schema_version": "2026-05-29",
        "document_type": "user_profile",
        "tenant_id": client_id,
        "user_id": user_id,
        "email": email,
        "display_name": f"{first_name} {last_name}".strip() or email,
        "first_name": first_name,
        "last_name": last_name,
        "role": "owner",
        "status": status,
        "auth": {
            "provider": "cognito",
            "cognito_username": email,
            "email_verified": status == "active",
            "mfa_enabled": False,
        },
        "created_at": now,
        "updated_at": now,
    }


def session_from_cognito_user(user, auth=None):
    attributes = {item["Name"]: item.get("Value", "") for item in user.get("UserAttributes", [])}
    user_id = attributes.get("sub") or user.get("Username") or attributes.get("email")
    client_id = attributes.get("custom:client_id") or attributes.get("custom:tenant_id") or user_id
    if not client_id:
        raise ValueError("Cognito user is missing a usable client_id.")
    auth = auth or {}
    return {
        "provider": "cognito",
        "client_id": client_id,
        "tenant_id": client_id,
        "user_id": user_id,
        "email": attributes.get("email") or user.get("Username"),
        "first_name": attributes.get("given_name", ""),
        "last_name": attributes.get("family_name", ""),
        "email_verified": attributes.get("email_verified") == "true",
        "id_token": auth.get("IdToken"),
        "access_token": auth.get("AccessToken"),
        "refresh_token": auth.get("RefreshToken"),
        "expires_in": auth.get("ExpiresIn"),
        "token_type": auth.get("TokenType"),
        "created_at": epoch(),
    }


def client_id_for(body, user_sub=None):
    provided = str(body.get("client_id") or body.get("tenant_id") or "").strip()
    if provided:
        return provided
    if user_sub:
        return user_sub
    return f"client_{uuid.uuid4().hex[:16]}"


def required(body, field):
    value = str(body.get(field) or "").strip()
    if not value:
        raise ValueError(f"{field} is required.")
    return value


def delivery(details):
    if not details:
        return None
    return {
        "destination": details.get("Destination"),
        "delivery_medium": details.get("DeliveryMedium"),
        "attribute_name": details.get("AttributeName"),
    }


def cognito_error(exc):
    code = exc.response.get("Error", {}).get("Code", "CognitoError")
    message = exc.response.get("Error", {}).get("Message", str(exc))
    status = 409 if code in {"UsernameExistsException", "AliasExistsException"} else 400
    return error_response(message, status_code=status, code=code)


def user_pool_id():
    value = os.environ.get("COGNITO_USER_POOL_ID", "")
    if not value:
        raise ValueError("COGNITO_USER_POOL_ID is not configured.")
    return value


def user_pool_client_id():
    value = os.environ.get("COGNITO_USER_POOL_CLIENT_ID", "")
    if not value:
        raise ValueError("COGNITO_USER_POOL_CLIENT_ID is not configured.")
    return value


def epoch():
    return int(time.time())


def cognito_client():
    import boto3

    return boto3.client("cognito-idp")


def is_cognito_client_error(exc):
    return hasattr(exc, "response") and isinstance(getattr(exc, "response", None), dict) and "Error" in exc.response

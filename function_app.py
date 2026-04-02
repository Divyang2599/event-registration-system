import azure.functions as func
import json
import os
import base64
import hashlib
import secrets
import re
import logging
from datetime import datetime
from azure.data.tables import TableServiceClient

# Configure logging for Azure Application Insights
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = func.FunctionApp()


# -----------------------------
# Helpers
# -----------------------------
def cors_headers(methods: str) -> dict:
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": methods,
        "Access-Control-Allow-Headers": "Content-Type"
    }


def json_response(payload: dict | list, status_code: int = 200, methods: str = "GET, POST, OPTIONS") -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
        headers=cors_headers(methods)
    )


def get_table_client(table_name: str):
    conn_str = os.environ["AzureStorageConnectionString"]
    service = TableServiceClient.from_connection_string(conn_str)
    table = service.get_table_client(table_name)
    try:
        table.create_table()
    except Exception:
        # Table may already exist
        pass
    return table


def normalize_email(email: str) -> str:
    return email.strip().lower()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return base64.b64encode(salt).decode() + ":" + base64.b64encode(pwd_hash).decode()


def verify_password(password: str, stored_value: str) -> bool:
    try:
        salt_b64, hash_b64 = stored_value.split(":")
        salt = base64.b64decode(salt_b64)
        expected_hash = base64.b64decode(hash_b64)
        provided_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
        return secrets.compare_digest(provided_hash, expected_hash)
    except Exception:
        return False


def get_user_by_email(email: str):
    users_table = get_table_client("users")
    normalized = normalize_email(email)

    try:
        return users_table.get_entity(partition_key="USER", row_key=normalized)
    except Exception:
        return None


def get_registration_entity(email: str, event: str):
    registrations_table = get_table_client("registrations")
    normalized_email = normalize_email(email)
    event_key = slugify(event)

    try:
        return registrations_table.get_entity(partition_key=normalized_email, row_key=event_key)
    except Exception:
        return None


# -----------------------------
# Signup
# -----------------------------
@app.route(route="signup", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def signup(req: func.HttpRequest) -> func.HttpResponse:
    methods = "POST, OPTIONS"

    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(methods))

    try:
        data = req.get_json()
        name = data.get("name", "").strip()
        email = normalize_email(data.get("email", ""))
        password = data.get("password", "").strip()

        logger.info(f"Signup attempt for email: {email}")

        if not name or not email or not password:
            logger.warning(f"Signup failed - missing fields for: {email}")
            return json_response({"error": "name, email and password are required"}, 400, methods)

        if len(password) < 6:
            logger.warning(f"Signup failed - password too short for: {email}")
            return json_response({"error": "Password must be at least 6 characters long"}, 400, methods)

        if get_user_by_email(email):
            logger.warning(f"Signup failed - email already exists: {email}")
            return json_response({"error": "An account with this email already exists"}, 409, methods)

        users_table = get_table_client("users")
        now = datetime.utcnow().isoformat()

        entity = {
            "PartitionKey": "USER",
            "RowKey": email,
            "Name": name,
            "Email": email,
            "PasswordHash": hash_password(password),
            "CreatedAt": now
        }

        users_table.create_entity(entity)
        logger.info(f"New user registered successfully: {email}")

        return json_response(
            {
                "message": "Account created successfully",
                "name": name,
                "email": email
            },
            201,
            methods
        )

    except ValueError:
        logger.error("Signup failed - Invalid JSON body")
        return json_response({"error": "Invalid JSON body"}, 400, methods)
    except Exception as e:
        logger.error(f"Signup failed with error: {str(e)}")
        return json_response({"error": str(e)}, 500, methods)


# -----------------------------
# Login
# -----------------------------
@app.route(route="login", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def login(req: func.HttpRequest) -> func.HttpResponse:
    methods = "POST, OPTIONS"

    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(methods))

    try:
        data = req.get_json()
        email = normalize_email(data.get("email", ""))
        password = data.get("password", "").strip()

        logger.info(f"Login attempt for email: {email}")

        if not email or not password:
            logger.warning(f"Login failed - missing credentials for: {email}")
            return json_response({"error": "email and password are required"}, 400, methods)

        user = get_user_by_email(email)
        if not user:
            logger.warning(f"Login failed - user not found: {email}")
            return json_response({"error": "Invalid email or password"}, 401, methods)

        stored_hash = user.get("PasswordHash", "")
        if not verify_password(password, stored_hash):
            logger.warning(f"Login failed - invalid password for: {email}")
            return json_response({"error": "Invalid email or password"}, 401, methods)

        logger.info(f"✅ User logged in successfully: {email}")

        return json_response(
            {
                "message": "Login successful",
                "name": user.get("Name"),
                "email": user.get("Email")
            },
            200,
            methods
        )

    except ValueError:
        logger.error("Login failed - Invalid JSON body")
        return json_response({"error": "Invalid JSON body"}, 400, methods)
    except Exception as e:
        logger.error(f"Login failed with error: {str(e)}")
        return json_response({"error": str(e)}, 500, methods)


# -----------------------------
# Register Event
# -----------------------------
@app.route(route="register", methods=["POST", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def register(req: func.HttpRequest) -> func.HttpResponse:
    methods = "POST, OPTIONS"

    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(methods))

    try:
        data = req.get_json()
        name = data.get("name", "").strip()
        email = normalize_email(data.get("email", ""))
        event = data.get("event", "").strip()

        logger.info(f"Event registration attempt: {email} -> {event}")

        if not name or not email or not event:
            logger.warning(f"Registration failed - missing fields for: {email}")
            return json_response({"error": "name, email and event are required"}, 400, methods)

        user = get_user_by_email(email)
        if not user:
            logger.warning(f"Registration failed - user not found: {email}")
            return json_response(
                {"error": "No account found for this email. Please sign up or log in first."},
                401,
                methods
            )

        existing = get_registration_entity(email, event)
        if existing:
            logger.warning(f"Registration failed - duplicate registration: {email} -> {event}")
            return json_response(
                {"error": "You have already registered for this event"},
                409,
                methods
            )

        registrations_table = get_table_client("registrations")
        now = datetime.utcnow().isoformat()

        entity = {
            "PartitionKey": email,
            "RowKey": slugify(event),
            "Name": user.get("Name"),
            "Email": email,
            "Event": event,
            "RegisteredAt": now
        }

        registrations_table.create_entity(entity)
        logger.info(f"Event registration successful: {email} -> {event}")

        return json_response(
            {"message": f"Registration successful for {user.get('Name')}"},
            201,
            methods
        )

    except ValueError:
        logger.error("Event registration failed - Invalid JSON body")
        return json_response({"error": "Invalid JSON body"}, 400, methods)
    except Exception as e:
        logger.error(f"Event registration failed with error: {str(e)}")
        return json_response({"error": str(e)}, 500, methods)


# -----------------------------
# My Registrations
# -----------------------------
@app.route(route="my_registrations", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def my_registrations(req: func.HttpRequest) -> func.HttpResponse:
    methods = "GET, OPTIONS"

    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(methods))

    try:
        email = normalize_email(req.params.get("email", ""))

        logger.info(f"Fetching registrations for: {email}")

        if not email:
            logger.warning("My registrations failed - missing email parameter")
            return json_response({"error": "email query parameter is required"}, 400, methods)

        registrations_table = get_table_client("registrations")

        # Efficient lookup for new records where PartitionKey = user email
        entities = list(registrations_table.query_entities(f"PartitionKey eq '{email}'"))

        result = []
        for e in entities:
            result.append({
                "name": e.get("Name"),
                "email": e.get("Email"),
                "event": e.get("Event") or e.get("PartitionKey"),
                "registeredAt": e.get("RegisteredAt")
            })

        # Sort newest first
        result.sort(key=lambda x: x.get("registeredAt", ""), reverse=True)

        logger.info(f"Retrieved {len(result)} registrations for: {email}")

        return json_response(result, 200, methods)

    except Exception as e:
        logger.error(f"My registrations failed with error: {str(e)}")
        return json_response({"error": str(e)}, 500, methods)


# -----------------------------
# Admin - All Registrations
# -----------------------------
@app.route(route="get_registrations", methods=["GET", "OPTIONS"], auth_level=func.AuthLevel.ANONYMOUS)
def get_registrations(req: func.HttpRequest) -> func.HttpResponse:
    methods = "GET, OPTIONS"

    if req.method == "OPTIONS":
        return func.HttpResponse(status_code=204, headers=cors_headers(methods))

    try:
        logger.info("Admin: Fetching all registrations")

        registrations_table = get_table_client("registrations")
        entities = list(registrations_table.list_entities())

        result = []
        for e in entities:
            result.append({
                "name": e.get("Name"),
                "email": e.get("Email"),
                "event": e.get("Event") or e.get("PartitionKey"),
                "registeredAt": e.get("RegisteredAt")
            })

        result.sort(key=lambda x: x.get("registeredAt", ""), reverse=True)

        logger.info(f"Admin: Retrieved {len(result)} total registrations")

        return json_response(result, 200, methods)

    except Exception as e:
        logger.error(f"Admin get registrations failed with error: {str(e)}")
        return json_response({"error": str(e)}, 500, methods)


# -----------------------------
# Health Check
# -----------------------------
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    """Health check endpoint for monitoring service availability"""
    try:
        logger.info("Health check initiated")
        
        # Test Table Storage connectivity
        get_table_client("users")
        
        logger.info("Health check passed")
        
        return func.HttpResponse(
            json.dumps({
                "status": "healthy",
                "service": "event-registration-api",
                "timestamp": datetime.utcnow().isoformat(),
                "database": "connected"
            }),
            status_code=200,
            mimetype="application/json"
        )
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return func.HttpResponse(
            json.dumps({
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }),
            status_code=503,
            mimetype="application/json"
        )

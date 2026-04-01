import azure.functions as func
import json
import uuid
import os
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient

app = func.FunctionApp()

# Connection setup
CONN_STR = os.environ.get("AzureStorageConnectionString")
service = TableServiceClient.from_connection_string(CONN_STR)
table_client = service.get_table_client("registrations")

def get_auth_user(req):
    """Helper to get user email from Azure EasyAuth headers"""
    # This header is automatically added by Azure after login
    return req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")

@app.route(route="register", methods=["POST", "OPTIONS"])
def register(req: func.HttpRequest) -> func.HttpResponse:
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    if req.method == "OPTIONS": return func.HttpResponse(status_code=204, headers=cors_headers)

    user_email = get_auth_user(req)
    if not user_email:
        return func.HttpResponse(json.dumps({"error": "Authentication Required"}), status_code=401, headers=cors_headers)

    try:
        data = req.get_json()
        # We use the authenticated email instead of a form input for security
        entity = {
            "PartitionKey": user_email, # Partition by User for fast 'My Events' lookups
            "RowKey": str(uuid.uuid4()),
            "Name": data.get("name"),
            "Email": user_email,
            "Event": data.get("event"),
            "RegisteredAt": datetime.now(timezone.utc).isoformat()
        }
        table_client.create_entity(entity)
        return func.HttpResponse(json.dumps({"message": "Registration successful"}), status_code=201, headers=cors_headers)
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, headers=cors_headers)

@app.route(route="get_my_registrations", methods=["GET", "OPTIONS"])
def get_my_registrations(req: func.HttpRequest) -> func.HttpResponse:
    cors_headers = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    if req.method == "OPTIONS": return func.HttpResponse(status_code=204, headers=cors_headers)

    user_email = get_auth_user(req)
    if not user_email:
        return func.HttpResponse(json.dumps({"error": "Unauthorized"}), status_code=401, headers=cors_headers)

    try:
        # Query only the data belonging to this user (the PartitionKey)
        entities = table_client.query_entities(query_filter=f"PartitionKey eq '{user_email}'")
        result = [{"event": e.Event, "registeredAt": e.RegisteredAt} for e in entities]
        return func.HttpResponse(json.dumps(result), status_code=200, headers=cors_headers)
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, headers=cors_headers)

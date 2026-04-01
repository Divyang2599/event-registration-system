import azure.functions as func
import json
import uuid
import os
from datetime import datetime, timezone
from azure.data.tables import TableServiceClient

app = func.FunctionApp()

# Connection setup - Client is initialized globally for connection pooling
CONN_STR = os.environ.get("AzureStorageConnectionString")
service = TableServiceClient.from_connection_string(CONN_STR)
table_client = service.get_table_client("registrations")

def get_auth_user(req):
    """Retrieves the authenticated user's email from EasyAuth headers."""
    return req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME")

@app.route(route="register", methods=["POST", "OPTIONS"])
def register(req: func.HttpRequest) -> func.HttpResponse:
    cors_headers = {
        "Access-Control-Allow-Origin": "*", 
        "Access-Control-Allow-Methods": "POST, OPTIONS", 
        "Access-Control-Allow-Headers": "Content-Type"
    }
    if req.method == "OPTIONS": 
        return func.HttpResponse(status_code=204, headers=cors_headers)

    user_email = get_auth_user(req)
    if not user_email:
        return func.HttpResponse(json.dumps({"error": "Login required"}), status_code=401, headers=cors_headers)

    try:
        data = req.get_json()
        # Architecture: PartitionKey = UserEmail for high-performance user-specific queries
        entity = {
            "PartitionKey": user_email,
            "RowKey": str(uuid.uuid4()),
            "Name": data.get("name"),
            "Email": user_email,
            "Event": data.get("event"),
            "RegisteredAt": datetime.now(timezone.utc).isoformat()
        }
        table_client.create_entity(entity)
        return func.HttpResponse(json.dumps({"message": f"Successfully registered for {data.get('event')}"}), status_code=201, headers=cors_headers)
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, headers=cors_headers)

@app.route(route="get_my_registrations", methods=["GET", "OPTIONS"])
def get_my_registrations(req: func.HttpRequest) -> func.HttpResponse:
    cors_headers = {
        "Access-Control-Allow-Origin": "*", 
        "Access-Control-Allow-Methods": "GET, OPTIONS", 
        "Access-Control-Allow-Headers": "Content-Type"
    }
    if req.method == "OPTIONS": 
        return func.HttpResponse(status_code=204, headers=cors_headers)

    user_email = get_auth_user(req)
    if not user_email:
        return func.HttpResponse(json.dumps({"error": "Unauthorized"}), status_code=401, headers=cors_headers)

    try:
        # Efficient O(1) lookup because we are filtering by PartitionKey
        entities = table_client.query_entities(query_filter=f"PartitionKey eq '{user_email}'")
        result = [{"name": e.get("Name"), "event": e.get("Event"), "registeredAt": e.get("RegisteredAt")} for e in entities]
        return func.HttpResponse(json.dumps(result), status_code=200, headers=cors_headers)
    except Exception as e:
        return func.HttpResponse(json.dumps({"error": str(e)}), status_code=500, headers=cors_headers)

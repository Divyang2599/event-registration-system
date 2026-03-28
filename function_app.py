import azure.functions as func
import json
import uuid
from datetime import datetime
from azure.data.tables import TableServiceClient
import os

app = func.FunctionApp()

@app.route(route="register", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
def register(req: func.HttpRequest) -> func.HttpResponse:
    try:
        data = req.get_json()
        name = data.get("name")
        email = data.get("email")
        event = data.get("event")

        if not name or not email or not event:
            return func.HttpResponse(
                json.dumps({"error": "name, email and event are required"}),
                status_code=400,
                mimetype="application/json"
            )

        conn_str = os.environ["AzureStorageConnectionString"]
        service = TableServiceClient.from_connection_string(conn_str)
        table = service.get_table_client("registrations")

        entity = {
            "PartitionKey": event,
            "RowKey": str(uuid.uuid4()),
            "Name": name,
            "Email": email,
            "RegisteredAt": datetime.utcnow().isoformat()
        }

        table.create_entity(entity)

        return func.HttpResponse(
            json.dumps({"message": f"Registration successful for {name}"}),
            status_code=201,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )


@app.route(route="get_registrations", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_registrations(req: func.HttpRequest) -> func.HttpResponse:
    try:
        conn_str = os.environ["AzureStorageConnectionString"]
        service = TableServiceClient.from_connection_string(conn_str)
        table = service.get_table_client("registrations")

        entities = list(table.list_entities())
        result = []
        for e in entities:
            result.append({
                "name": e.get("Name"),
                "email": e.get("Email"),
                "event": e.get("PartitionKey"),
                "registeredAt": e.get("RegisteredAt")
            })

        return func.HttpResponse(
            json.dumps(result),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*"}
        )

    except Exception as e:
        return func.HttpResponse(
            json.dumps({"error": str(e)}),
            status_code=500,
            mimetype="application/json"
        )
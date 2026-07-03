"""
GraphQL API for the Fire Safety Dashboard.

Exposes a read query layer over the existing Supabase-backed helpers plus
mutations for managing webhook alert subscriptions. Served at ``/graphql``
(POST for queries, GET for the GraphiQL explorer) and gated behind the admin
session, consistent with the rest of the admin surface.
"""

import graphene
from flask import Blueprint, request, jsonify, session, Response

import webhooks as wh
from DatabaseScript import (
    get_region_id,
    get_node_info,
    get_node_history,
    get_node_region,
    get_nodes_for_dashboard,
    get_drones_for_region,
    get_admin_stats,
    REGION_NAME_TO_ID,
)

graphql_bp = Blueprint("graphql_bp", __name__)

HEADQUARTERS = wh.HEADQUARTERS


def _load_all_nodes():
    return get_nodes_for_dashboard(HEADQUARTERS) or []


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #
class Region(graphene.ObjectType):
    region_id = graphene.String()
    name = graphene.String()


class Node(graphene.ObjectType):
    node_id = graphene.String()
    title = graphene.String()
    location = graphene.String()
    description = graphene.String()
    is_parent = graphene.Boolean()
    region_id = graphene.String()
    danger_level = graphene.Int()
    lat = graphene.Float()
    lng = graphene.Float()


class SensorReading(graphene.ObjectType):
    node_id = graphene.String()
    timestamp = graphene.String()
    danger_level = graphene.Int()
    temperature = graphene.Float()
    humidity = graphene.Float()
    gas_and_smoke = graphene.Float()
    wind_speed = graphene.Float()


class Drone(graphene.ObjectType):
    drone_id = graphene.String()
    name = graphene.String()
    model = graphene.String()
    operational_status = graphene.String()
    home_lat = graphene.Float()
    home_lng = graphene.Float()
    roam_radius_km = graphene.Float()


class Alert(graphene.ObjectType):
    node_id = graphene.String()
    title = graphene.String()
    location = graphene.String()
    region_id = graphene.String()
    danger_level = graphene.Int()
    threshold = graphene.Int()
    lat = graphene.Float()
    lng = graphene.Float()


class Webhook(graphene.ObjectType):
    id = graphene.String()
    url = graphene.String()
    min_danger_level = graphene.Int()
    region = graphene.String()
    description = graphene.String()
    enabled = graphene.Boolean()
    created_at = graphene.String()
    last_triggered_at = graphene.String()
    last_status = graphene.Int()
    last_error = graphene.String()
    delivery_count = graphene.Int()


class DeliveryResult(graphene.ObjectType):
    webhook_id = graphene.String()
    url = graphene.String()
    ok = graphene.Boolean()
    status = graphene.Int()
    error = graphene.String()


class EvaluateResult(graphene.ObjectType):
    generated_at = graphene.String()
    enabled_webhooks = graphene.Int()
    triggered_webhooks = graphene.Int()
    matched_nodes = graphene.Int()
    deliveries = graphene.List(DeliveryResult)


def _webhook_type(sub):
    if not sub:
        return None
    return Webhook(**{k: sub.get(k) for k in (
        "id", "url", "min_danger_level", "region", "description", "enabled",
        "created_at", "last_triggered_at", "last_status", "last_error", "delivery_count",
    )})


# --------------------------------------------------------------------------- #
# Query
# --------------------------------------------------------------------------- #
class Query(graphene.ObjectType):
    regions = graphene.List(Region)
    nodes = graphene.List(Node, region=graphene.String())
    node = graphene.Field(Node, node_id=graphene.String(required=True))
    sensor_readings = graphene.List(SensorReading, node_id=graphene.String(required=True))
    drones = graphene.List(Drone, region=graphene.String(required=True))
    alerts = graphene.List(Alert, threshold=graphene.Int(default_value=wh.MIN_LEVEL))
    webhooks = graphene.List(Webhook)
    admin_stats = graphene.JSONString()

    def resolve_regions(root, info):
        regions = [Region(region_id=rid, name=name) for name, rid in REGION_NAME_TO_ID.items()]
        regions.insert(0, Region(region_id=None, name=HEADQUARTERS))
        return regions

    def resolve_nodes(root, info, region=None):
        region = region or HEADQUARTERS
        return [Node(**{k: n.get(k) for k in (
            "node_id", "title", "location", "description", "is_parent",
            "region_id", "danger_level", "lat", "lng")})
            for n in (get_nodes_for_dashboard(region) or [])]

    def resolve_node(root, info, node_id):
        info_row = get_node_info(node_id)
        if not info_row:
            return None
        history = get_node_history(node_id) or []
        if history:
            info_row = {**info_row, **history[0]}
        if not info_row.get("region_id"):
            info_row["region_id"] = get_node_region(node_id)
        return Node(**{k: info_row.get(k) for k in (
            "node_id", "title", "location", "description", "is_parent",
            "region_id", "danger_level", "lat", "lng")})

    def resolve_sensor_readings(root, info, node_id):
        rows = get_node_history(node_id) or []
        return [SensorReading(**{k: r.get(k) for k in (
            "node_id", "timestamp", "danger_level", "temperature",
            "humidity", "gas_and_smoke", "wind_speed")}) for r in rows]

    def resolve_drones(root, info, region):
        return [Drone(**{k: d.get(k) for k in (
            "drone_id", "name", "model", "operational_status",
            "home_lat", "home_lng", "roam_radius_km")})
            for d in (get_drones_for_region(region) or [])]

    def resolve_alerts(root, info, threshold):
        return [Alert(**a) for a in wh.current_alerts(_load_all_nodes, threshold)]

    def resolve_webhooks(root, info):
        return [_webhook_type(s) for s in wh.list_webhooks()]

    def resolve_admin_stats(root, info):
        return get_admin_stats()


# --------------------------------------------------------------------------- #
# Mutations
# --------------------------------------------------------------------------- #
class CreateWebhook(graphene.Mutation):
    class Arguments:
        url = graphene.String(required=True)
        min_danger_level = graphene.Int(default_value=wh.DEFAULT_THRESHOLD)
        region = graphene.String()
        description = graphene.String()

    Output = Webhook

    def mutate(root, info, url, min_danger_level=wh.DEFAULT_THRESHOLD, region=None, description=""):
        sub = wh.create_webhook(url, min_danger_level=min_danger_level,
                                region=region, description=description)
        return _webhook_type(sub)


class DeleteWebhook(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)

    Output = graphene.Boolean

    def mutate(root, info, id):
        return wh.delete_webhook(id)


class SetWebhookEnabled(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)
        enabled = graphene.Boolean(required=True)

    Output = Webhook

    def mutate(root, info, id, enabled):
        return _webhook_type(wh.set_enabled(id, enabled))


class TestWebhook(graphene.Mutation):
    class Arguments:
        id = graphene.String(required=True)

    Output = DeliveryResult

    def mutate(root, info, id):
        result = wh.test_webhook(id)
        return DeliveryResult(**result) if result else None


class EvaluateAlerts(graphene.Mutation):
    Output = EvaluateResult

    def mutate(root, info):
        summary = wh.evaluate_and_dispatch(_load_all_nodes, get_region_id)
        summary["deliveries"] = [DeliveryResult(**d) for d in summary["deliveries"]]
        return EvaluateResult(**summary)


class Mutation(graphene.ObjectType):
    create_webhook = CreateWebhook.Field()
    delete_webhook = DeleteWebhook.Field()
    set_webhook_enabled = SetWebhookEnabled.Field()
    test_webhook = TestWebhook.Field()
    evaluate_alerts = EvaluateAlerts.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)


# --------------------------------------------------------------------------- #
# HTTP transport
# --------------------------------------------------------------------------- #
_GRAPHIQL_HTML = """<!DOCTYPE html>
<html lang="el">
<head>
  <meta charset="utf-8" />
  <title>GraphQL — Πίνακας Πυρασφάλειας</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="https://unpkg.com/graphiql@3/graphiql.min.css" />
  <style>html,body,#graphiql{height:100%;margin:0;}</style>
</head>
<body>
  <div id="graphiql">Φόρτωση GraphiQL…</div>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
  <script crossorigin src="https://unpkg.com/graphiql@3/graphiql.min.js"></script>
  <script>
    const fetcher = GraphiQL.createFetcher({ url: window.location.pathname });
    const root = ReactDOM.createRoot(document.getElementById('graphiql'));
    root.render(React.createElement(GraphiQL, { fetcher }));
  </script>
</body>
</html>"""


def _unauthorized():
    return jsonify({"error": "unauthorized"}), 401


@graphql_bp.route("/graphql", methods=["GET", "POST"])
def graphql_server():
    if not session.get("is_admin"):
        if request.method == "GET":
            return Response("Απαιτείται σύνδεση διαχειριστή για το GraphQL.", status=401)
        return _unauthorized()

    if request.method == "GET":
        return Response(_GRAPHIQL_HTML, mimetype="text/html")

    data = request.get_json(silent=True) or {}
    query = data.get("query")
    if not query:
        return jsonify({"errors": [{"message": "Missing query"}]}), 400

    result = schema.execute(
        query,
        variable_values=data.get("variables"),
        operation_name=data.get("operationName"),
    )
    response = {"data": result.data}
    if result.errors:
        response["errors"] = [{"message": str(e)} for e in result.errors]
        return jsonify(response), 200
    return jsonify(response)

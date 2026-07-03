import os
import json
import traceback
from flask import Flask, render_template, jsonify, abort, redirect, url_for, request, session, flash
from DatabaseScript import (
    get_node_info, get_node_history, get_node_region,
    get_parent_node_reports, get_nodes_for_dashboard, get_region_id, get_nodes_by_region,
    get_drones_for_region, get_drone_info, get_drone_region,
    get_admin_stats,
)
from drone_sim import step_all, snapshot
import webhooks as wh

app = Flask(__name__)

# GraphQL is an optional add-on. If its dependency (graphene) is not installed
# yet on the host, keep the rest of the dashboard running instead of failing to
# boot the whole WSGI app. Install requirements.txt to enable /graphql.
try:
    from graphql_api import graphql_bp
    app.register_blueprint(graphql_bp)
    GRAPHQL_ENABLED = True
except Exception as _graphql_import_error:  # pragma: no cover - environment dependent
    GRAPHQL_ENABLED = False
    app.logger.warning(
        "GraphQL API disabled (could not import graphql_api): "
        f"{_graphql_import_error}. Run 'pip install -r requirements.txt' to enable it."
    )

# Set a fixed secret key for development (use environment variable in production)
app.config['SECRET_KEY'] = '123123123'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True

# Admin panel access code (override with ADMIN_PANEL_CODE in production)
ADMIN_CODE = os.getenv('ADMIN_PANEL_CODE', '123')


def _validate_drone_access(drone_id):
    region_name = session.get('region')
    if not region_name:
        return False
    if region_name == 'Αρχηγείο / Ε.Σ.Κ.Ε.ΔΙ.Κ.':
        return True
    current_region_id = get_region_id(region_name)
    drone_region = get_drone_region(drone_id)
    return current_region_id is not None and drone_region == current_region_id


@app.route('/favicon.ico')
def favicon():
    return '', 204


@app.route('/')
def index():
    return redirect(url_for('login'))


@app.route('/login')
def login():
    session.clear()
    return render_template('login.html')


@app.route('/set_region', methods=['POST'])
def set_region():
    try:
        region = request.form.get('region')
        if not region:
            flash('Παρακαλώ επιλέξτε μια Περιφερειακή Πυροσβεστική Διοίκηση')
            return redirect(url_for('login'))

        from DatabaseScript import _normalize_region_name

        region = _normalize_region_name(region)
        session["region"] = region
        session["region_id"] = get_region_id(region)
        session.modified = True
        return redirect(url_for("dashboard"))
    except Exception as e:
        app.logger.error(f"Error in set_region: {str(e)}")
        flash('Προέκυψε σφάλμα κατά την επιλογή περιοχής. Παρακαλώ δοκιμάστε ξανά.')
        return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/admin_login', methods=['POST'])
def admin_login():
    code = (request.form.get('admin_code') or '').strip()
    if code != ADMIN_CODE:
        flash('Λάθος κωδικός διαχειριστή.')
        return redirect(url_for('login'))
    session.clear()
    session['is_admin'] = True
    session.modified = True
    return redirect(url_for('admin'))


@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    try:
        from DatabaseScript import REGION_NAME_TO_ID
        stats = get_admin_stats()
        regions = [{"name": name, "region_id": rid} for name, rid in REGION_NAME_TO_ID.items()]
        return render_template('admin.html', stats=stats, regions=regions,
                               graphql_enabled=GRAPHQL_ENABLED)
    except Exception as e:
        app.logger.error(f"Error loading admin panel: {e}\n{traceback.format_exc()}")
        abort(500)


@app.route('/api/admin/stats')
def api_admin_stats():
    if not session.get('is_admin'):
        return jsonify({"error": "unauthorized"}), 401
    try:
        return jsonify(get_admin_stats())
    except Exception as e:
        app.logger.error(f"/api/admin/stats failed: {e}")
        return jsonify({"error": "Failed to load stats", "details": str(e)}), 500


def _load_all_nodes():
    """All nodes (with latest danger_level + region) — used by the alert engine."""
    from DatabaseScript import get_nodes_for_dashboard
    return get_nodes_for_dashboard(wh.HEADQUARTERS) or []


def _admin_required_json():
    """Return an error response tuple when the caller is not an admin, else None."""
    if not session.get('is_admin'):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.route('/api/webhooks', methods=['GET', 'POST'])
def api_webhooks():
    guard = _admin_required_json()
    if guard:
        return guard
    if request.method == 'GET':
        return jsonify({"webhooks": wh.list_webhooks()})
    try:
        payload = request.get_json(silent=True) or request.form
        sub = wh.create_webhook(
            url=payload.get('url'),
            min_danger_level=payload.get('min_danger_level', wh.DEFAULT_THRESHOLD),
            region=payload.get('region'),
            description=payload.get('description', ''),
        )
        return jsonify({"webhook": sub}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"/api/webhooks create failed: {e}")
        return jsonify({"error": "Failed to create webhook", "details": str(e)}), 500


@app.route('/api/webhooks/<webhook_id>', methods=['DELETE', 'PATCH'])
def api_webhook_detail(webhook_id):
    guard = _admin_required_json()
    if guard:
        return guard
    if request.method == 'DELETE':
        return (jsonify({"deleted": True}) if wh.delete_webhook(webhook_id)
                else (jsonify({"error": "not found"}), 404))
    payload = request.get_json(silent=True) or request.form
    updated = wh.set_enabled(webhook_id, str(payload.get('enabled')).lower() in ('1', 'true', 'on', 'yes'))
    return jsonify({"webhook": updated}) if updated else (jsonify({"error": "not found"}), 404)


@app.route('/api/webhooks/<webhook_id>/test', methods=['POST'])
def api_webhook_test(webhook_id):
    guard = _admin_required_json()
    if guard:
        return guard
    result = wh.test_webhook(webhook_id)
    return jsonify({"result": result}) if result else (jsonify({"error": "not found"}), 404)


@app.route('/api/alerts')
def api_alerts():
    guard = _admin_required_json()
    if guard:
        return guard
    try:
        from DatabaseScript import get_region_id  # noqa: F401 (kept for symmetry)
        threshold = int(request.args.get('threshold', wh.MIN_LEVEL))
        return jsonify({"alerts": wh.current_alerts(_load_all_nodes, threshold)})
    except Exception as e:
        app.logger.error(f"/api/alerts failed: {e}")
        return jsonify({"error": "Failed to load alerts", "details": str(e)}), 500


@app.route('/api/alerts/evaluate', methods=['POST'])
def api_alerts_evaluate():
    guard = _admin_required_json()
    if guard:
        return guard
    try:
        from DatabaseScript import get_region_id
        summary = wh.evaluate_and_dispatch(_load_all_nodes, get_region_id)
        return jsonify(summary)
    except Exception as e:
        app.logger.error(f"/api/alerts/evaluate failed: {e}")
        return jsonify({"error": "Failed to evaluate alerts", "details": str(e)}), 500


@app.route('/dashboard')
def dashboard():
    if 'region' not in session:
        return redirect(url_for('login'))

    try:
        region_name = session["region"]
        # Always derive from region name — stale session["region_id"] caused FR1 nodes on other regions
        region_id = get_region_id(region_name)
        if session.get("region_id") != region_id:
            session["region_id"] = region_id
            session.modified = True

        nodes = get_nodes_for_dashboard(region_name, region_id=region_id)
        if nodes is None:
            nodes = []

        allowed_node_ids = [n["node_id"] for n in nodes if n.get("node_id")]
        print(f"Dashboard region={region_name!r} region_id={region_id!r} nodes={allowed_node_ids}")
        return render_template(
            "index.html",
            region=region_name,
            region_id=region_id,
            nodes=nodes,
            allowed_node_ids=allowed_node_ids,
        )
    except Exception as e:
        app.logger.error(f"Error loading dashboard: {str(e)}")
        abort(500)


@app.route('/node/<node_id>')
def node(node_id):
    if 'region' not in session:
        return redirect(url_for('login'))

    try:
        supabase_node_id = f"N{node_id.replace('.', '_')}"
        node_info = get_node_info(supabase_node_id)

        # Ensure the node exists
        if not node_info:
            abort(404, description=f"Node {node_id} not found")

        # Secure region validation
        current_region_id = get_region_id(session['region'])
        node_region = get_node_region(supabase_node_id)

        # Allow access if:
        # 1. User is from headquarters (current_region_id is None)
        # OR
        # 2. Node's region matches user's region
        if current_region_id is not None and node_region != current_region_id:
            abort(404, description=f"Node {node_id} not found in this region")

        # Merge with latest readings
        history_data = get_node_history(supabase_node_id)
        latest_data = history_data[0] if history_data else {}
        node_info.update(latest_data)

        return render_template('node.html', node=node_info)
    except Exception as e:
        app.logger.error(f"Error in /node/{node_id}: {str(e)}")
        abort(500)


@app.route('/nodes')
def nodes_info():
    if 'region' not in session:
        return redirect(url_for('login'))

    try:
        region_name = session["region"]
        region_id = get_region_id(region_name)
        session["region_id"] = region_id
        nodes = get_nodes_for_dashboard(region_name, region_id=region_id) or []
        return render_template(
            "nodes.html",
            nodes=nodes,
            region=region_name,
            region_id=region_id,
        )
    except Exception as e:
        app.logger.error(f"Error rendering nodes: {str(e)}")
        abort(500)


@app.route('/parent/<node_id>')
def parent_node(node_id):
    if 'region' not in session:
        return redirect(url_for('login'))

    try:
        supabase_node_id = f"N{node_id.replace('.', '_')}"
        node_info = get_node_info(supabase_node_id)

        if not node_info:
            abort(404, description=f"Parent node {node_id} not found")

        current_region_id = get_region_id(session['region'])
        node_region = get_node_region(supabase_node_id)
        if current_region_id is not None and node_region != current_region_id:
            abort(404, description=f"Parent node {node_id} not found in this region")

        # Get report data
        reports = get_parent_node_reports(supabase_node_id)

        return render_template('parent_node.html',
                               parent=node_info,
                               reports=reports,
                               region=session['region'])
    except Exception as e:
        app.logger.error(f"Error in /parent/{node_id}: {str(e)}")
        abort(500)


@app.route('/history/<node_id>')
def history(node_id):
    if 'region' not in session:
        return redirect(url_for('login'))

    try:
        # Accept both "1.1" and "N1_1" formats.
        supabase_node_id = node_id if node_id.startswith('N') else f"N{node_id.replace('.', '_')}"
        node_info = get_node_info(supabase_node_id)

        if node_info:
            current_region_id = get_region_id(session['region'])
            node_region = get_node_region(supabase_node_id)
            if current_region_id is not None and node_region != current_region_id:
                abort(404, description=f"Node {node_id} not found in this region")

        # Fallback: if no metadata, use latest sensor reading
        if not node_info:
            history_data = get_node_history(supabase_node_id)
            if history_data:
                node_info = {"node_id": supabase_node_id, **history_data[0]}
            else:
                abort(404, description=f"Node {node_id} not found")

        else:
            history_data = get_node_history(supabase_node_id)

        return render_template('history.html',
                               node=node_info,
                               readings=history_data or [],
                               message=None if history_data else "No historical data available")
    except Exception as e:
        app.logger.error(f"Error in /history/{node_id}: {str(e)}")
        abort(500)


@app.route('/drone')
def drone_info():
    if 'region' not in session:
        return redirect(url_for('login'))
    try:
        drones = get_drones_for_region(session['region']) or []
        drones_json = json.dumps(drones, ensure_ascii=False, default=str)
        return render_template(
            "drone.html",
            drones=drones,
            drones_json=drones_json,
            region=session["region"],
            region_id=session.get("region_id") or get_region_id(session["region"]),
        )
    except Exception as e:
        app.logger.error(f"Error loading drone page: {e}\n{traceback.format_exc()}")
        drones_json = json.dumps([], ensure_ascii=False)
        return render_template(
            'drone.html',
            drones=[],
            drones_json=drones_json,
            region=session.get('region', ''),
            error_message="Δεν ήταν δυνατή η φόρτωση των ΣΜΗΕΑ. Εμφανίζεται κενή λίστα.",
        )


@app.route('/api/drones')
def api_drones():
    try:
        region_name = request.args.get('region') or session.get('region')
        if not region_name:
            return jsonify({"error": "region not specified"}), 400
        drones = get_drones_for_region(region_name) or []
        step_all(drones)
        live_drones = []
        for d in drones:
            drone_id = d.get("drone_id")
            if not drone_id:
                continue
            live_drones.append(snapshot(drone_id, d))
        return jsonify({"drones": live_drones, "region": region_name, "count": len(live_drones)})
    except Exception as e:
        app.logger.error(f"/api/drones failed: {e}")
        return jsonify({"error": "Failed to fetch drones", "details": str(e)}), 500


@app.route('/api/drone_telemetry')
def drone_telemetry_legacy():
    """Backward-compatible endpoint used by older drone.html scripts."""
    try:
        region_name = session.get('region')
        if not region_name:
            return jsonify({"error": "region not specified"}), 400
        drones = get_drones_for_region(region_name) or []
        if not drones:
            return jsonify({"error": "No drones found"}), 404
        drone_id = drones[0].get("drone_id")
        if not drone_id:
            return jsonify({"error": "No drones found"}), 404
        step_all(drones)
        return jsonify(snapshot(drone_id, drones[0]))
    except Exception as e:
        app.logger.error(f"/api/drone_telemetry failed: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Failed to get drone telemetry", "details": str(e)}), 500


@app.route('/api/drone_telemetry/<drone_id>')
def drone_telemetry(drone_id):
    try:
        if not _validate_drone_access(drone_id):
            return jsonify({"error": "Drone not found in this region"}), 404
        info = get_drone_info(drone_id)
        if not info:
            return jsonify({"error": "Drone not found"}), 404
        return jsonify(snapshot(drone_id, info))
    except Exception as e:
        app.logger.error(f"/api/drone_telemetry/{drone_id} failed: {e}")
        return jsonify({"error": "Failed to get drone telemetry", "details": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
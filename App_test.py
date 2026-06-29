import os
import json
import time
import secrets
import traceback
from flask import Flask, render_template, jsonify, abort, redirect, url_for, request, session, flash
from DatabaseScript import (
    get_node_info, get_node_history, get_node_region,
    get_parent_node_reports, get_nodes_for_dashboard, get_region_id, get_nodes_by_region,
    get_drones_for_region, get_drone_info, get_drone_region,
    get_admin_stats,
)
from drone_sim import step_all, snapshot


def _env_flag(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ('1', 'true', 'yes', 'on')


app = Flask(__name__)

# Secret key: override with SECRET_KEY in production. Falls back to a per-process
# random key if neither SECRET_KEY nor the legacy dev default is desired.
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', '123123123')
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.jinja_env.auto_reload = True

# Session cookie hardening. SESSION_COOKIE_SECURE defaults to false so local HTTP
# development works; set SESSION_COOKIE_SECURE=true (and FORCE_HTTPS=true) in
# production (e.g. on PythonAnywhere, which serves over HTTPS).
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=_env_flag('SESSION_COOKIE_SECURE', False),
)

# Admin panel access code (override with ADMIN_PANEL_CODE in production)
ADMIN_CODE = os.getenv('ADMIN_PANEL_CODE', '123')

# Brute-force protection for the admin login.
ADMIN_MAX_ATTEMPTS = int(os.getenv('ADMIN_MAX_ATTEMPTS', '5'))
ADMIN_LOCKOUT_SECONDS = int(os.getenv('ADMIN_LOCKOUT_SECONDS', '300'))
_admin_login_attempts = {}  # client_ip -> {count, first, locked_until}

# Content Security Policy. Allows the third-party resources the app actually uses
# (Leaflet from unpkg, Font Awesome from cdnjs, OpenStreetMap tiles) while blocking
# arbitrary external scripts/connections and framing of the site.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' https://unpkg.com",
    "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdnjs.cloudflare.com",
    "img-src 'self' data: https://*.tile.openstreetmap.org https://unpkg.com",
    "font-src 'self' https://cdnjs.cloudflare.com",
    "connect-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def _client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'unknown'


def _request_is_https():
    return request.is_secure or request.headers.get('X-Forwarded-Proto', '') == 'https'


# ---------------------------------------------------------------------------
# CSRF protection (no external dependency)
# ---------------------------------------------------------------------------
def generate_csrf_token():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return session['_csrf_token']


@app.context_processor
def _inject_csrf_token():
    return {'csrf_token': generate_csrf_token}


@app.before_request
def _force_https():
    """Optional redirect to HTTPS (enable with FORCE_HTTPS=true in production)."""
    if _env_flag('FORCE_HTTPS', False) and not _request_is_https():
        if request.url.startswith('http://'):
            return redirect(request.url.replace('http://', 'https://', 1), code=301)


@app.before_request
def _csrf_protect():
    if request.method == 'POST':
        expected = session.get('_csrf_token')
        provided = request.form.get('csrf_token', '')
        if not expected or not provided or not secrets.compare_digest(str(expected), str(provided)):
            abort(400, description='Invalid or missing CSRF token')


@app.after_request
def _set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = CONTENT_SECURITY_POLICY
    if _request_is_https():
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response


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
    # Log out app state but preserve flashed messages and the CSRF token so error
    # feedback (e.g. wrong admin code / lockout) is visible on the rendered page.
    for key in ('region', 'region_id', 'is_admin'):
        session.pop(key, None)
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
    ip = _client_ip()
    now = time.time()
    record = _admin_login_attempts.get(ip)

    # Reject while locked out.
    if record and record.get('locked_until', 0) > now:
        remaining = int(record['locked_until'] - now)
        flash(f'Πολλές αποτυχημένες προσπάθειες. Δοκιμάστε ξανά σε {remaining} δευτερόλεπτα.')
        return redirect(url_for('login'))

    code = (request.form.get('admin_code') or '').strip()
    if not secrets.compare_digest(code, ADMIN_CODE):
        # Reset the window if the previous attempts are stale.
        if not record or (now - record.get('first', now)) > ADMIN_LOCKOUT_SECONDS:
            record = {'count': 0, 'first': now, 'locked_until': 0}
        record['count'] += 1
        if record['count'] >= ADMIN_MAX_ATTEMPTS:
            record['locked_until'] = now + ADMIN_LOCKOUT_SECONDS
            record['count'] = 0
            flash(f'Πολλές αποτυχημένες προσπάθειες. Ο λογαριασμός κλειδώθηκε για {ADMIN_LOCKOUT_SECONDS // 60} λεπτά.')
        else:
            attempts_left = ADMIN_MAX_ATTEMPTS - record['count']
            flash(f'Λάθος κωδικός διαχειριστή. Απομένουν {attempts_left} προσπάθειες.')
        _admin_login_attempts[ip] = record
        return redirect(url_for('login'))

    # Successful login clears any failed-attempt state.
    _admin_login_attempts.pop(ip, None)
    session.clear()
    session['is_admin'] = True
    session.modified = True
    return redirect(url_for('admin'))


@app.route('/privacy')
def privacy():
    return render_template('privacy.html')


@app.errorhandler(400)
def bad_request(e):
    return render_template('error.html', code=400,
                           message='Μη έγκυρο αίτημα. Ανανεώστε τη σελίδα και δοκιμάστε ξανά.'), 400


@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', code=404,
                           message='Η σελίδα που ζητήσατε δεν βρέθηκε.'), 404


@app.errorhandler(500)
def server_error(e):
    return render_template('error.html', code=500,
                           message='Προέκυψε εσωτερικό σφάλμα. Παρακαλώ δοκιμάστε ξανά αργότερα.'), 500


@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect(url_for('login'))
    try:
        stats = get_admin_stats()
        return render_template('admin.html', stats=stats)
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
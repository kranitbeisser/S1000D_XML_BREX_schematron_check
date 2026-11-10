"""
S1000D Validator - Reporting & Logging (v8.2)

PURPOSE:
Advanced reporting logic for generating high-fidelity HTML Dashboards,
XML reports, and text summaries.
"""

import os
import sys
import logging
from lxml import etree
import sqlite3
import csv
import base64
import json
import re

# Standard log format for console and text file
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] [%(filename_short)s]: %(message)s"


class ContextFilter(logging.Filter):
    """Ensures all expected S1000D attributes exist on every log record."""
    def filter(self, record):
        attributes = [
            'filename_short', 'dm_code', 'rpc', 'originator',
            'schema_location', 'error_type', 'location', 'xpath'
        ]
        for attr in attributes:
            if not hasattr(record, attr):
                setattr(record, attr, 'N/A')
        return True


def setup_logging(log_dir, timestamp, debug_mode, write_log_file=False):
    """Sets up the global logging environment for the main process."""
    os.makedirs(log_dir, exist_ok=True)
    level = logging.DEBUG if debug_mode else logging.INFO

    active_handlers = [logging.StreamHandler(sys.stdout)]

    if write_log_file:
        log_file = os.path.join(log_dir, f"{timestamp}_process.log")
        active_handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format=LOG_FORMAT,
        handlers=active_handlers
    )

    logger = logging.getLogger()
    logger.addFilter(ContextFilter())


def init_database(log_dir, timestamp):
    """Initializes the local SQLite database using a massive-scale relational schema."""
    db_path = os.path.join(log_dir, f"{timestamp}_validation.db")
    conn = sqlite3.connect(db_path)

    # High-performance PRAGMAs for massive Inserts with Crash-Safety
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")

    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            filename TEXT,
            dm_code TEXT,
            info_code TEXT,
            rpc TEXT,
            originator TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level INTEGER,
            levelname TEXT,
            error_type TEXT,
            rule_id TEXT,
            message TEXT,
            UNIQUE(error_type, rule_id, message)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS Locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER,
            error_id INTEGER,
            line_number TEXT,
            xpath TEXT,
            attribute TEXT,
            FOREIGN KEY(file_id) REFERENCES Files(id),
            FOREIGN KEY(error_id) REFERENCES Errors(id)
        )
    ''')
    # Indices for lightning-fast JOINS
    cur.execute("CREATE INDEX IF NOT EXISTS idx_loc_file ON Locations(file_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_loc_error ON Locations(error_id)")

    conn.commit()
    return conn, db_path


def write_text_reports(summary, timestamp, log_dir):
    """Generates simple .txt lists of valid and invalid files."""
    valid_path = os.path.join(log_dir, f'{timestamp}_valid_files.txt')
    invalid_path = os.path.join(log_dir, f'{timestamp}_invalid_files.txt')

    with open(valid_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary.get('valid_files', [])))

    with open(invalid_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(summary.get('invalid_files', [])))


def write_xml_report(records, summary, timestamp, log_dir):
    """Generates a machine-readable XML report of all violations."""
    root = etree.Element("ValidationReport", timestamp=timestamp)
    sum_el = etree.SubElement(root, "Summary")
    for k, v in summary.items():
        if isinstance(v, (int, str)):
            etree.SubElement(sum_el, k).text = str(v)

    viols = etree.SubElement(root, "Violations")
    if summary.get('db_path'):
        conn = sqlite3.connect(summary['db_path'])
        cur = conn.cursor()
        cur.execute("""
            SELECT f.filename, e.error_type, e.message, l.xpath, l.line_number, l.attribute
            FROM Locations l
            JOIN Files f ON l.file_id = f.id
            JOIN Errors e ON l.error_id = e.id
        """)
        for f_name, e_type, msg, xp, line, attr in cur.fetchall():
            v = etree.SubElement(viols, "Violation", file=f_name, type=e_type)
            if line and line != 'N/A':
                v.set("line", str(line))
            if attr and attr != 'N/A':
                v.set("attribute", str(attr))
            etree.SubElement(v, "Message").text = msg
            etree.SubElement(v, "XPath").text = xp
        conn.close()

    tree = etree.ElementTree(root)
    xml_path = os.path.join(log_dir, f"{timestamp}_report.xml")
    tree.write(xml_path, pretty_print=True, encoding='utf-8', xml_declaration=True)


def write_csv_report(timestamp, log_dir, db_path):
    """Generates a full CSV export of all validation logs for deep analysis."""
    csv_path = os.path.join(log_dir, f"{timestamp}_logs.csv")

    if not os.path.exists(db_path):
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT f.timestamp, e.levelname, f.filename, e.error_type, e.rule_id, f.dm_code,
               f.info_code, f.rpc, f.originator, e.message, l.line_number, l.xpath, l.attribute
        FROM Locations l
        JOIN Files f ON l.file_id = f.id
        JOIN Errors e ON l.error_id = e.id
    """)

    headers = [
        "Time", "Level", "File", "Type", "Rule ID", "DM Code",
        "Info Code", "RPC", "Originator", "Message", "Line", "XPath Location", "Attribute"
    ]

    with open(csv_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        writer.writerows(cur.fetchall())

    conn.close()
    return csv_path


def write_junit_report(summary, timestamp, log_dir):
    """Generates a standard JUnit XML report for CI/CD pipeline test runners (GitLab CI, GitHub Actions, Jenkins)."""
    db_path = summary.get('db_path')
    if not db_path or not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT id, filename, dm_code FROM Files ORDER BY id ASC")
    files = cur.fetchall()

    cur.execute("""
        SELECT l.file_id, e.levelname, e.error_type, e.rule_id, e.message, l.line_number, l.xpath, l.attribute
        FROM Locations l
        JOIN Errors e ON l.error_id = e.id
        ORDER BY l.id ASC
    """)
    findings_by_file = {}
    for file_id, levelname, err_type, rule_id, msg, line_no, xpath, attr in cur.fetchall():
        findings_by_file.setdefault(file_id, []).append({
            'levelname': levelname,
            'error_type': err_type,
            'rule_id': rule_id,
            'message': msg,
            'line': line_no,
            'xpath': xpath,
            'attribute': attr
        })
    conn.close()

    total_tests = str(summary.get('total', len(files)))
    total_failures = str(summary.get('invalid', 0))

    testsuites = etree.Element("testsuites", name="S1000D Validation Suite", tests=total_tests, failures=total_failures)
    testsuite = etree.SubElement(
        testsuites, "testsuite",
        name="S1000D Data Modules",
        tests=total_tests,
        failures=total_failures,
        timestamp=timestamp
    )

    for file_id, filename, dm_code in files:
        if filename == "CONFIGURATION_AUDIT":
            continue
        tc = etree.SubElement(
            testsuite, "testcase",
            name=filename,
            classname=f"S1000D.{dm_code if dm_code and dm_code != 'N/A' else 'DataModule'}"
        )
        file_findings = findings_by_file.get(file_id, [])
        for f in file_findings:
            if f['levelname'] in ('ERROR', 'CRITICAL', 'VIOLATION'):
                fail_el = etree.SubElement(
                    tc, "failure",
                    type=f"{f['error_type']}:{f['rule_id']}",
                    message=f['message']
                )
                fail_el.text = f"Line: {f['line']} | XPath: {f['xpath']} | Attribute: {f['attribute']}"

    junit_path = os.path.join(log_dir, f"{timestamp}_junit.xml")
    tree = etree.ElementTree(testsuites)
    tree.write(junit_path, pretty_print=True, encoding='utf-8', xml_declaration=True)
    return junit_path


def write_sarif_report(summary, timestamp, log_dir):
    """Generates a SARIF v2.1.0 report for GitHub Code Scanning / Azure DevOps / IDE inline annotations."""
    db_path = summary.get('db_path')
    if not db_path or not os.path.exists(db_path):
        return None

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT f.filename, f.dm_code, e.levelname, e.error_type, e.rule_id, e.message, l.line_number, l.xpath
        FROM Locations l
        JOIN Files f ON l.file_id = f.id
        JOIN Errors e ON l.error_id = e.id
        ORDER BY l.id ASC
    """)
    rows = cur.fetchall()
    conn.close()

    rules_map = {}
    results = []

    for filename, dm_code, levelname, err_type, rule_id, msg, line_str, xpath in rows:
        r_id = rule_id if rule_id and rule_id != 'N/A' else err_type
        if r_id not in rules_map:
            rules_map[r_id] = {
                "id": r_id,
                "name": f"{err_type}_{r_id}",
                "shortDescription": {"text": f"S1000D {err_type} Rule ({r_id})"},
                "properties": {"category": err_type}
            }

        sarif_level = "error" if levelname in ("ERROR", "CRITICAL", "VIOLATION") else (
            "warning" if levelname == "WARNING" else "note"
        )

        start_line = 1
        if line_str:
            m = re.search(r'(\d+)', str(line_str))
            if m:
                start_line = max(1, int(m.group(1)))

        results.append({
            "ruleId": r_id,
            "level": sarif_level,
            "message": {"text": f"[{err_type}] {msg} (XPath: {xpath})"},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": filename},
                    "region": {"startLine": start_line}
                }
            }]
        })

    sarif_doc = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "S1000D XML BREX & Schematron Validator",
                    "version": "8.7.0",
                    "rules": list(rules_map.values())
                }
            },
            "results": results
        }]
    }

    sarif_path = os.path.join(log_dir, f"{timestamp}_report.sarif.json")
    with open(sarif_path, "w", encoding="utf-8") as f:
        json.dump(sarif_doc, f, indent=2)
    return sarif_path


def write_html_report(records, summary, timestamp, log_dir):
    """Generates the interactive S1000D Validation Dashboard loader."""
    html_path = os.path.join(log_dir, f"{timestamp}_report.html")
    db_path = summary.get('db_path')
    db_filename = os.path.basename(db_path) if db_path else f"{timestamp}_validation.db"

    # Compute relative paths dynamically between report, viewer, and database
    app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    viewer_abs = os.path.join(app_root, "S1000D_App_Viewer.html")
    try:
        viewer_rel = os.path.relpath(viewer_abs, os.path.abspath(log_dir)).replace('\\', '/')
    except ValueError:
        viewer_rel = "../S1000D_App_Viewer.html"

    try:
        actual_db_abs = os.path.abspath(db_path) if db_path else os.path.join(os.path.abspath(log_dir), db_filename)
        db_rel_from_viewer = os.path.relpath(actual_db_abs, os.path.dirname(viewer_abs)).replace('\\', '/')
    except ValueError:
        db_rel_from_viewer = f"logs/{db_filename}"

    # Embed Base64 DB payload for zero-CORS file:// transfer via postMessage (< 25 MB)
    db_b64 = ""
    if db_path and os.path.exists(db_path):
        try:
            if os.path.getsize(db_path) < 25 * 1024 * 1024:
                with open(db_path, "rb") as dbf:
                    db_b64 = base64.b64encode(dbf.read()).decode("ascii")
        except Exception:
            db_b64 = ""

    # Pre-calculated stats for the summary view
    total = summary.get('total', 1)
    inv = summary.get('invalid', 0)
    valid = summary.get('valid', 0)
    warnings = summary.get('warnings', 0)

    denom = max(inv, (
        summary.get('by_schema', 0) +
        summary.get('by_brex', 0) +
        summary.get('by_schematron', 0) +
        summary.get('by_resource', 0) +
        summary.get('by_reference', 0) +
        summary.get('by_naming', 0) +
        summary.get('by_config', 0) +
        summary.get('by_syntax', 0)
    ), 1)

    def get_p(key):
        return min(100.0, (summary.get(key, 0) / denom * 100.0)) if denom > 0 else 0.0

    sch_p = get_p('by_schema')
    brx_p = get_p('by_brex')
    smt_p = get_p('by_schematron')
    res_p = get_p('by_resource')
    ref_p = get_p('by_reference')
    nam_p = get_p('by_naming')
    cfg_p = get_p('by_config')
    syntax_p = get_p('by_syntax')

    template = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>S1000D Validation Report - {timestamp}</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {{
            --primary: #1a73e8;
            --slate-50: #f8fafc;
            --slate-100: #f1f5f9;
            --slate-200: #e2e8f0;
            --slate-800: #1e293b;
            --danger: #ef4444;
            --success: #10b981;
            --warning: #f59e0b;
            --info: #0ea5e9;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background: var(--slate-50);
            margin: 0;
            padding: 40px;
            color: var(--slate-800);
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            padding: 24px;
            border-radius: 12px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            margin-bottom: 20px;
            border: 1px solid var(--slate-200);
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
        }}
        .stat-val {{
            font-size: 2rem;
            font-weight: 800;
            display: block;
        }}
        .stat-label {{
            font-size: 0.75rem;
            color: #64748b;
            text-transform: uppercase;
            font-weight: 700;
        }}
        .btn-launch {{
            background: var(--primary);
            color: white;
            padding: 16px 32px;
            border-radius: 8px;
            text-decoration: none;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            gap: 10px;
            font-size: 1.1rem;
            border: none;
            cursor: pointer;
        }}
        .btn-launch:hover {{
            background: #1557b0;
            transform: translateY(-1px);
        }}
        .footer {{
            margin-top: 40px;
            font-size: 0.85rem;
            color: #94a3b8;
            border-top: 1px solid var(--slate-200);
            padding-top: 20px;
        }}
        .bar-bg {{
            background: #eee;
            height: 6px;
            border-radius: 3px;
            margin-bottom: 12px;
            overflow: hidden;
        }}
        .bar-fill {{
            height: 100%;
            border-radius: 3px;
        }}
        .bar-label {{
            display: flex;
            justify-content: space-between;
            margin-bottom: 4px;
            font-size: 0.8rem;
            font-weight: 600;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 S1000D Validation <span style="font-weight:400; opacity:0.6;">Summary</span></h1>
        <div style="text-align: right;"><span class="stat-label">Execution Time</span><br><b>{timestamp}</b></div>
    </div>

    <div class="card" style="background: var(--slate-800); color: white; display: flex; align-items: center; justify-content: space-between; padding: 40px;">
        <div>
            <h2 style="margin:0 0 10px 0;">Validation Complete</h2>
            <p style="opacity:0.7; margin:0;">Deep analysis is available in the desktop viewer.</p>
        </div>
        <script>
            window.__S1000D_DB_B64__ = "{db_b64}";
            window.__S1000D_DB_NAME__ = "{db_filename}";
            window.addEventListener("message", function(event) {{
                if (event.data && event.data.type === "S1000D_REQUEST_DB" && window.__S1000D_DB_B64__) {{
                    event.source.postMessage({{
                        type: "S1000D_DB_PAYLOAD",
                        filename: window.__S1000D_DB_NAME__,
                        b64: window.__S1000D_DB_B64__
                    }}, "*");
                }}
            }});
            function openViewer() {{
                const dbPath = encodeURIComponent('{db_rel_from_viewer}');
                window.open(`{viewer_rel}?db=${{dbPath}}`, '_blank');
            }}
        </script>
        <button onclick="openViewer()" class="btn-launch">🔍 Open Analyst Workspace</button>
    </div>

    <div class="grid">
        <div class="card">
            <span class="stat-label">Data Modules</span>
            <span class="stat-val">{total}</span>
            <div style="margin-top:15px; display:flex; gap:20px;">
                <div><span class="stat-label" style="color:var(--success)">Valid</span><br><b>{valid}</b></div>
                <div><span class="stat-label" style="color:var(--danger)">Invalid</span><br><b>{invalid}</b></div>
                <div><span class="stat-label" style="color:var(--warning)">Warnings</span><br><b>{warnings}</b></div>
            </div>
        </div>
        <div class="card">
            <span class="stat-label">Finding Distribution</span>
            <div style="margin-top:15px;">
                <div class="bar-label"><span>XML Syntax ({syntax_c})</span><span>{syntax_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:#ec4899; width:{syntax_p}%;"></div></div>

                <div class="bar-label"><span>Schema / XSD ({sch_c})</span><span>{sch_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:var(--danger); width:{sch_p}%;"></div></div>

                <div class="bar-label"><span>BREX Logic ({brx_c})</span><span>{brx_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:var(--warning); width:{brx_p}%;"></div></div>

                <div class="bar-label"><span>Schematron ({smt_c})</span><span>{smt_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:#a855f7; width:{smt_p}%;"></div></div>

                <div class="bar-label"><span>Resources / ICN ({res_c})</span><span>{res_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:var(--info); width:{res_p}%;"></div></div>

                <div class="bar-label"><span>DM References ({ref_c})</span><span>{ref_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:#818cf8; width:{ref_p}%;"></div></div>

                <div class="bar-label"><span>Filename / DMC ({nam_c})</span><span>{nam_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:#14b8a6; width:{nam_p}%;"></div></div>

                <div class="bar-label"><span>Configuration ({cfg_c})</span><span>{cfg_p:.1f}%</span></div>
                <div class="bar-bg"><div class="bar-fill" style="background:#6366f1; width:{cfg_p}%;"></div></div>
            </div>
        </div>
        <div class="card">
            <span class="stat-label">Database Origin</span>
            <span class="stat-val" style="font-size:1.2rem; margin-top:10px; word-break:break-all;">{db_filename}</span>
            <p style="font-size:0.8rem; opacity:0.6; margin-top:10px;">Click "Open Analyst Workspace" above or drag this file into the viewer for deep inspection.</p>
        </div>
    </div>

    <div class="footer">
        S1000D XML BREX/Schematron Validator &copy; 2026 - Optimized for high-volume analysis.
    </div>
</body>
</html>"""

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(template.format(
            timestamp=timestamp, total=total, valid=valid, invalid=inv, warnings=warnings,
            sch_p=sch_p, brx_p=brx_p, smt_p=smt_p, res_p=res_p, ref_p=ref_p, nam_p=nam_p, cfg_p=cfg_p, syntax_p=syntax_p,
            sch_c=summary.get('by_schema', 0), brx_c=summary.get('by_brex', 0), smt_c=summary.get('by_schematron', 0),
            res_c=summary.get('by_resource', 0), ref_c=summary.get('by_reference', 0), nam_c=summary.get('by_naming', 0),
            cfg_c=summary.get('by_config', 0), syntax_c=summary.get('by_syntax', 0),
            db_filename=db_filename, viewer_rel=viewer_rel, db_rel_from_viewer=db_rel_from_viewer, db_b64=db_b64
        ))


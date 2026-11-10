#!/usr/bin/env python3

"""
S1000D Batch Validator - v8.6.1 (Granular Engine Control)
"""

import sys
import os
import argparse
import time
import logging
import multiprocessing
import json
from datetime import datetime, timedelta
from collections import Counter
from pathlib import Path
import re
from lxml import etree

from s1000d_validator import __version__
from s1000d_validator.reporting import (
    setup_logging, init_database, write_html_report, write_xml_report,
    write_text_reports, write_csv_report, write_junit_report, write_sarif_report
)
from s1000d_validator.core import process_file, init_worker
from s1000d_validator.audit import validate_brex_file, validate_schematron_file
from s1000d_validator.utils import load_csdb_manifest

# --- History Persistence (v8.3.3) ---
HISTORY_FILE = Path(".validator_history.json")


def normalize_settings(settings):
    if isinstance(settings, dict):
        normalized = {}
        for k, v in settings.items():
            k_lower = k.lower().strip()
            # Key translation
            if k_lower == 'motoren':
                new_key = 'engines'
            elif k_lower == 'integrität':
                new_key = 'integrity'
            elif k_lower in ('aktiviert', 'enabled'):
                new_key = 'enabled'
            elif k_lower in ('schweregrad', 'severity'):
                new_key = 'severity'
            elif k_lower in ('referenzprüfung', 'referenzprüfungen', 'reference_check', 'reference_checks'):
                new_key = 'reference_checks'
            elif k_lower in ('referenzprüfung_aktiviert', 'referenzprüfungen_aktiviert', 'reference_checks_enabled'):
                new_key = 'reference_checks_enabled'
            else:
                new_key = k

            # Recursive normalization
            norm_val = normalize_settings(v)

            # Value translation for string values
            if isinstance(norm_val, str):
                v_upper = norm_val.upper().strip()
                if v_upper == 'WARNUNG':
                    norm_val = 'WARNING'
                elif v_upper == 'FEHLER':
                    norm_val = 'ERROR'
                elif v_upper == 'INFO':
                    norm_val = 'INFO'
            
            normalized[new_key] = norm_val
        return normalized
    elif isinstance(settings, list):
        return [normalize_settings(x) for x in settings]
    else:
        return settings


def load_history():
    """Reads the last used configuration from a local file."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_history(input_dir, config_dir, baseline=None):
    """Saves the current configuration to local history."""
    try:
        data = {
            'input_dir': str(Path(input_dir).resolve()),
            'config_dir': str(Path(config_dir).resolve()),
            'baseline': str(Path(baseline).resolve()) if baseline else None,
            'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception:
        pass


def parse_arguments():
    """Parses CLI arguments or shows help if missing."""
    parser = argparse.ArgumentParser(description=f"S1000D Batch Validator (v{__version__})")
    parser.add_argument("-v", "--version", action="version", version=f"S1000D Validator v{__version__}")
    parser.add_argument("-i", "--input", dest='input_dir', help="Input folder containing XML/DM files.")
    parser.add_argument("-c", "--config", dest='config_dir',
                        help="Config folder containing BREX (.xml) and Schematron (.sch).")
    parser.add_argument("-l", "--log-dir", default="logs", help="Folder for reports/logs (Default: 'logs').")
    parser.add_argument("-s", "--schema-dir", default=None, help="Folder for .xsd files (Default: config/schemas).")
    parser.add_argument("--schema-mode", choices=['local', 'online', 'auto'], default='auto',
                        help="Schema resolution mode: 'local' (only directory), 'online' (always fetch), "
                             "'auto' (directory first, fallback to online for referenced).")
    parser.add_argument("--allowed-versions", default=None,
                        help="Comma-separated list of allowed S1000D versions (e.g. '4.1' or '4.1,4.2').")
    parser.add_argument("-w", "--max-workers", type=int, default=None, help="Number of CPU cores to use.")
    parser.add_argument("-b", "--baseline", help="Path to baseline.json for error suppression")
    parser.add_argument("--csdb-manifest", default=None,
                        help="Path to external CSDB manifest (TXT/CSV/JSON) of known DMCs and ICNs")
    parser.add_argument("--fail-on-warning", action="store_true",
                        help="Return non-zero exit code if warnings (level >= 30) are found")
    parser.add_argument("--no-schema", action="store_true", help="Skip XML Schema (XSD) validation engine")
    parser.add_argument("--no-brex", action="store_true", help="Skip BREX validation engine")
    parser.add_argument("--no-sch", "--no-schematron", dest="no_sch", action="store_true",
                        help="Skip Schematron validation engine")
    parser.add_argument("--no-integrity", action="store_true", help="Skip Link/Resource integrity check")
    parser.add_argument("--no-reference-checks", action="store_true", help="Skip DM Reference integrity checks")
    parser.add_argument("--no-resource-checks", action="store_true", help="Skip Illustration/Multimedia Resource integrity checks")
    parser.add_argument("--brex-info-code", default="022", help="S1000D Info Code for BREX data modules (Default: '022')")
    parser.add_argument("--brex-mode", choices=['project', 'chain', 'ignore'], default='project',
                        help="BREX Selection: 'project' (all in folder), 'chain' (only referenced), "
                             "'ignore' (referenced, ignore missing files).")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging.")
    parser.add_argument("--no-validation", dest="validation_enabled", action="store_false",
                        help="Disable all validation stages.")
    parser.add_argument("--strict-config", action="store_true",
                        help="Abort validation run if there are any configuration audit warnings or errors.")

    # Report Output Configuration
    parser.add_argument("--no-html", dest="out_html", action="store_false",
                        help="Disable generating the HTML Dashboard.")
    parser.add_argument("--xml", dest="out_xml", action="store_true",
                        help="Generate the XML report for CI/CD pipelines.")
    parser.add_argument("--junit", dest="out_junit", action="store_true",
                        help="Generate JUnit XML report for CI/CD test runners.")
    parser.add_argument("--sarif", dest="out_sarif", action="store_true",
                        help="Generate SARIF v2.1.0 report for GitHub Actions / Azure DevOps / IDEs.")
    parser.add_argument("--csv", dest="out_csv", action="store_true",
                        help="Generate CSV logs for deep analysis (CSV Analyst).")
    parser.add_argument("--txt", dest="out_txt", action="store_true",
                        help="Generate the TXT valid/invalid list reports.")
    parser.add_argument("--log", dest="out_log", action="store_true",
                        help="Write all raw terminal logs to a .log file.")

    if len(sys.argv) == 1:
        print("\n--- INTERACTIVE MODE (No arguments provided) ---")
        history = load_history()

        print(f"Loaded history from {history.get('last_run', 'Never')}.\n")

        input_dir = ""
        def_input = history.get('input_dir', './DMs')
        if not os.path.exists(def_input):
            def_input = "."
        while not os.path.exists(input_dir):
            prompt = f"Enter Input XML Folder [{def_input}]: "
            input_dir = input(prompt).strip() or def_input
            if not os.path.exists(input_dir):
                print(f"[!] Path does not exist: {input_dir}")

        config_dir = ""
        def_config = history.get('config_dir', './Rules')
        if not os.path.exists(def_config):
            def_config = "."
        while not os.path.exists(config_dir):
            prompt = f"Enter Config Rule Folder [{def_config}]: "
            config_dir = input(prompt).strip() or def_config
            if not os.path.exists(config_dir):
                print(f"[!] Path does not exist: {config_dir}")

        baseline = history.get('baseline', '')
        prompt = f"Enter Baseline (Suppression) JSON [None/Enter or '{baseline}']: "
        b_input = input(prompt).strip() or baseline

        # Engine preferences (History)
        use_schema = history.get('use_schema', True)
        use_brex = history.get('use_brex', True)
        use_sch = history.get('use_sch', True)
        use_int = history.get('use_int', True)
        use_ref_checks = history.get('use_ref_checks', True)
        schema_mode = history.get('schema_mode', 'auto')
        allowed_versions = history.get('allowed_versions', '')
        strict_config = history.get('strict_config', False)

        print("\nEngine Selection (Current Settings):")
        print(f"1. Schema (XSD):    {'[ON]' if use_schema else '[OFF]'}")
        print(f"2. BREX Validation: {'[ON]' if use_brex else '[OFF]'}")
        print(f"3. Schematron:      {'[ON]' if use_sch else '[OFF]'}")
        print(f"4. Integrity:       {'[ON]' if use_int else '[OFF]'}")
        print(f"5. Reference Checks:{'[ON]' if use_ref_checks else '[OFF]'}")
        toggle = input("\nToggle engines? (e.g. '1,4' to flip 1 and 4) [Enter to skip]: ").strip()
        if toggle:
            for part in toggle.split(','):
                p_trimmed = part.strip()
                if p_trimmed == '1':
                    use_schema = not use_schema
                if p_trimmed == '2':
                    use_brex = not use_brex
                if p_trimmed == '3':
                    use_sch = not use_sch
                if p_trimmed == '4':
                    use_int = not use_int
                if p_trimmed == '5':
                    use_ref_checks = not use_ref_checks

        # Save session to history automatically
        try:
            data = {
                'input_dir': str(Path(input_dir).resolve()),
                'config_dir': str(Path(config_dir).resolve()),
                'baseline': str(Path(b_input).resolve()) if b_input and os.path.exists(b_input) else None,
                'use_schema': use_schema, 'use_brex': use_brex, 'use_sch': use_sch, 'use_int': use_int,
                'use_ref_checks': use_ref_checks,
                'schema_mode': schema_mode,
                'allowed_versions': allowed_versions,
                'strict_config': strict_config,
                'last_run': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

        print("\nStarting validation with provided paths...\n")
        args_list = ["-i", input_dir, "-c", config_dir]
        if b_input and os.path.exists(b_input):
            args_list.extend(["-b", b_input])
        if not use_schema:
            args_list.append("--no-schema")
        if not use_brex:
            args_list.append("--no-brex")
        if not use_sch:
            args_list.append("--no-sch")
        if not use_int:
            args_list.append("--no-integrity")
        if not use_ref_checks:
            args_list.append("--no-reference-checks")
        args_list.extend(["--schema-mode", schema_mode])
        if allowed_versions:
            args_list.extend(["--allowed-versions", allowed_versions])
        if strict_config:
            args_list.append("--strict-config")
        return parser.parse_args(args_list)

    return parser.parse_args()


def print_progress_bar(iteration, total, start_time, prefix='', suffix='', length=40):
    """Custom progress bar with ETA."""
    percent = ("{0:.1f}").format(100 * (iteration / float(total)))
    filled_length = int(length * iteration // total)
    bar = '#' * filled_length + '-' * (length - filled_length)

    elapsed = time.time() - start_time
    if iteration > 0:
        total_est = (elapsed / iteration * total)
        eta = str(timedelta(seconds=int(total_est - elapsed)))
    else:
        eta = "Calculating..."

    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% {suffix} (ETA: {eta}) ')
    sys.stdout.flush()


def main():
    print(f"--- S1000D Validator v{__version__} Initializing ---")
    args = parse_arguments()
    start_time = time.time()
    run_timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')

    # Resolve paths (and additional validation)
    if not args.input_dir or not args.config_dir:
        print("\n[ERROR] Missing mandatory paths. Use -i (Input) and -c (Config) to start validation.")
        return

    input_path = Path(args.input_dir).resolve()
    config_path = Path(args.config_dir).resolve()

    if not input_path.exists():
        print(f"\n[ERROR] Input directory missing: {input_path}")
        return

    if not config_path.exists():
        print(f"\n[ERROR] Config directory missing: {config_path}")
        return

    # Project-Specific Settings Discovery (v8.4.1)
    project_settings = {}
    config_json_path = config_path / "validator_settings.json"
    if config_json_path.exists():
        try:
            with open(config_json_path, 'r', encoding='utf-8') as f:
                project_settings = json.load(f)
                project_settings = normalize_settings(project_settings)
                print(f"Loaded project configuration from {config_json_path.name}")
        except Exception as e:
            print(f"[!] Failed to parse project configuration: {e}")

    # Merge project settings into args (CLI overrides file)
    engine_overrides = project_settings.get("engines", {})
    if "schema" in engine_overrides:
        if args.no_schema is False:
            args.no_schema = not engine_overrides["schema"].get("enabled", True)
        args.schema_severity = engine_overrides["schema"].get("severity", "ERROR")
    else:
        args.schema_severity = "ERROR"

    if "brex" in engine_overrides:
        if args.no_brex is False:
            args.no_brex = not engine_overrides["brex"].get("enabled", True)
        args.brex_severity = engine_overrides["brex"].get("severity", "ERROR")
    if "schematron" in engine_overrides:
        if args.no_sch is False:
            args.no_sch = not engine_overrides["schematron"].get("enabled", True)
        args.sch_severity = engine_overrides["schematron"].get("severity", "ERROR")
    if "integrity" in engine_overrides:
        if args.no_integrity is False:
            args.no_integrity = not engine_overrides["integrity"].get("enabled", True)
        args.integrity_severity = engine_overrides["integrity"].get("severity", "WARNING")

    # Merge project settings for reference checks:
    ref_checks_disabled_by_config = False
    if "reference_checks_enabled" in project_settings:
        ref_checks_disabled_by_config = not project_settings["reference_checks_enabled"]
    elif "no_reference_checks" in project_settings:
        ref_checks_disabled_by_config = project_settings["no_reference_checks"]

    if "integrity" in engine_overrides:
        int_cfg = engine_overrides["integrity"]
        if isinstance(int_cfg, dict):
            if "reference_checks_enabled" in int_cfg:
                ref_checks_disabled_by_config = not int_cfg["reference_checks_enabled"]
            elif "reference_checks" in int_cfg:
                rc_cfg = int_cfg["reference_checks"]
                if isinstance(rc_cfg, dict):
                    if "enabled" in rc_cfg:
                        ref_checks_disabled_by_config = not rc_cfg["enabled"]
                elif isinstance(rc_cfg, bool):
                    ref_checks_disabled_by_config = not rc_cfg

    if args.no_reference_checks is False:
        args.no_reference_checks = ref_checks_disabled_by_config

    # Merge project settings for resource checks:
    res_checks_disabled_by_config = False
    if "resource_checks_enabled" in project_settings:
        res_checks_disabled_by_config = not project_settings["resource_checks_enabled"]
    elif "no_resource_checks" in project_settings:
        res_checks_disabled_by_config = project_settings["no_resource_checks"]

    if "integrity" in engine_overrides:
        int_cfg = engine_overrides["integrity"]
        if isinstance(int_cfg, dict):
            if "resource_checks_enabled" in int_cfg:
                res_checks_disabled_by_config = not int_cfg["resource_checks_enabled"]
            elif "resource_checks" in int_cfg:
                rc_cfg = int_cfg["resource_checks"]
                if isinstance(rc_cfg, dict):
                    if "enabled" in rc_cfg:
                        res_checks_disabled_by_config = not rc_cfg["enabled"]
                elif isinstance(rc_cfg, bool):
                    res_checks_disabled_by_config = not rc_cfg

    if args.no_resource_checks is False:
        args.no_resource_checks = res_checks_disabled_by_config

    # Merge project settings for brex_info_code:
    if "brex_info_code" in project_settings:
        if not getattr(args, 'brex_info_code', None) or args.brex_info_code == '022':
            args.brex_info_code = str(project_settings["brex_info_code"])

    args.brex_mappings = project_settings.get("brex_mappings", {})

    # Merge project settings into args
    if "schema_mode" in project_settings:
        if not hasattr(args, 'schema_mode') or args.schema_mode == 'auto':
            args.schema_mode = project_settings["schema_mode"]
    if "allowed_s1000d_versions" in project_settings:
        if not getattr(args, 'allowed_versions', None):
            args.allowed_s1000d_versions = project_settings["allowed_s1000d_versions"]
    if "strict_config" in project_settings:
        if getattr(args, 'strict_config', False) is False:
            args.strict_config = project_settings["strict_config"]
    if "fail_on_warning" in project_settings:
        if getattr(args, 'fail_on_warning', False) is False:
            args.fail_on_warning = bool(project_settings["fail_on_warning"])
    if "csdb_manifest" in project_settings:
        if not getattr(args, 'csdb_manifest', None):
            args.csdb_manifest = project_settings["csdb_manifest"]

    # Normalize allowed versions to a list of strings
    allowed_versions_list = []
    raw_versions = getattr(args, 'allowed_versions', None) or getattr(args, 'allowed_s1000d_versions', None)
    if raw_versions:
        if isinstance(raw_versions, list):
            allowed_versions_list = [str(v).strip() for v in raw_versions]
        else:
            allowed_versions_list = [v.strip() for v in str(raw_versions).split(',')]
    args.allowed_versions = allowed_versions_list

    # Logging
    print(f"Configuring logging in {args.log_dir}...")
    setup_logging(args.log_dir, run_timestamp, args.debug, args.out_log)

    # Baseline parsing
    baseline_rules = []
    if args.baseline:
        b_path = Path(args.baseline).resolve()
        if b_path.exists():
            try:
                with open(b_path, 'r', encoding='utf-8') as f:
                    baseline_data = json.load(f)
                    baseline_rules = baseline_data.get('ignores', [])
                print(f"Loaded {len(baseline_rules)} baseline rules from {b_path.name}.")
            except Exception as e:
                print(f"[!] Failed to parse baseline file: {e}")

    # Resolve schema directory
    schema_dir = Path(args.schema_dir).resolve() if args.schema_dir else config_path / "schemas"

    # Pre-compile schemas once for performance (v8.7.1)
    precompiled_els, precompiled_attrs = set(), set()
    if schema_dir.is_dir() and not args.no_brex and not args.no_sch:
        print("Pre-compiling schemas for configuration audit...")
        try:
            from s1000d_validator.utils import compile_schema_elements_and_attributes
            precompiled_els, precompiled_attrs = compile_schema_elements_and_attributes(schema_dir)
            print(f"-> Pre-compiled {len(precompiled_els)} elements and "
                  f"{len(precompiled_attrs)} attributes from schema folder.")
        except Exception as e:
            print(f"[!] Warning: Schema pre-compilation failed: {e}")

    # Rule Collection
    print("Collecting validation rules from config folder...")
    brex_files_raw = [str(f) for f in config_path.iterdir() if f.is_file() and f.suffix.lower() == '.xml']
    sch_files = [str(f) for f in config_path.iterdir() if f.is_file() and f.suffix.lower() == '.sch']
    print(f"-> Found {len(brex_files_raw)} BREX and {len(sch_files)} Schematron files in config.")

    # Configuration Audit (v8.4.1)
    brex_files = []
    config_audit_errors = []
    if not args.no_brex:
        for b in brex_files_raw:
            errs = validate_brex_file(
                b,
                schema_dir=schema_dir,
                schema_mode=args.schema_mode,
                allowed_versions=allowed_versions_list,
                precompiled_elements=precompiled_els,
                precompiled_attributes=precompiled_attrs
            )
            if errs:
                print(f"[!] Rule Audit Violation in {Path(b).name}: {len(errs)} issues found.")
                for e in errs:
                    print(f"    - {e['message']}")
                    config_audit_errors.append({'file': Path(b).name, 'error': e})
            brex_files.append({'path': b, 'is_config': True})

    if not args.no_sch:
        for s in sch_files:
            errs = validate_schematron_file(
                s,
                schema_dir=schema_dir,
                schema_mode=args.schema_mode,
                allowed_versions=allowed_versions_list,
                precompiled_elements=precompiled_els
            )
            if errs:
                print(f"[!] Rule Audit Violation in {Path(s).name}: {len(errs)} issues found.")
                for e in errs:
                    print(f"    - {e['message']}")
                    config_audit_errors.append({'file': Path(s).name, 'error': e})

    # Abort if configuration errors exist in project rules (before scanning input directories)
    strict_config = getattr(args, 'strict_config', False) or project_settings.get("strict_config", False)
    abort_threshold = 30 if strict_config else 40
    blocking_errors = [e for e in config_audit_errors if e['error'].get('level', 0) >= abort_threshold]
    if blocking_errors:
        print(f"\n[FATAL] Configuration Audit failed with {len(blocking_errors)} blocking issues "
              f"(abort threshold level >= {abort_threshold}).")
        print("Please resolve these rule/schema configuration issues before validating data modules.")
        sys.exit(1)

    print("Configuration rules audited successfully.")

    # Consolidated File Scanning (Single os.walk Pass) (v8.7.0)
    print(f"Scanning {input_path} for target files, resources, and input BREX files...")
    file_list = []
    available_resources = set()
    input_brex_files = []
    available_dmcs = set()

    for root_dir, _, files in os.walk(input_path):
        for f in files:
            f_lower = f.lower()
            full_p = os.path.join(root_dir, f)
            if f_lower.endswith(('.xml', '.dm')):
                file_list.append(full_p)

                # Check if it's a BREX file by using info code pre-filter, then parsing XML
                is_brex = False
                brex_info_code = getattr(args, 'brex_info_code', '022')
                if brex_info_code in f:
                    try:
                        parser = etree.XMLParser(recover=True, resolve_entities=False)
                        tree = etree.parse(full_p, parser)
                        if tree.xpath("//*[local-name()='content']/*[local-name()='brex']"):
                            is_brex = True
                    except Exception:
                        pass
                if is_brex:
                    # Avoid duplicates if the same file is in config and input
                    if not any(Path(full_p).name.lower() == Path(x).name.lower() for x in brex_files_raw):
                        input_brex_files.append(full_p)

                # Quick Filename-based DMC discovery
                name_match = re.match(r"^(?:DMC|PMC|DMLC)-(.*?)_.*?\..*$", f, re.I)
                if name_match:
                    available_dmcs.add(name_match.group(1).upper().replace("_", "-"))

            elif f_lower.endswith(('.cgm', '.svg', '.png', '.jpg', '.pdf')):
                available_resources.add(Path(f).stem.upper())

    total_files = len(file_list)
    if total_files == 0:
        print("\n[!] No XML/DM files found. Check your input path.")
        return

    print(f"-> Total target files to process: {total_files}")
    print(f"-> Discovered {len(available_dmcs)} DMs, {len(input_brex_files)} additional BREX files, "
          f"and {len(available_resources)} resource files.")

    # Include config-directory BREX DMCs in available_dmcs so <brexDmRef> does not trigger false LINK_BROKEN
    for bf in brex_files_raw:
        bf_name = Path(bf).name
        bf_match = re.match(r"^(?:DMC|PMC|DMLC)-(.*?)(?:_.*)?\..*$", bf_name, re.I)
        if bf_match:
            available_dmcs.add(bf_match.group(1).upper().replace("_", "-"))

    # Load optional external CSDB Manifest (v8.7.0)
    if getattr(args, 'csdb_manifest', None):
        m_path = Path(args.csdb_manifest)
        if not m_path.is_absolute() and (config_path / m_path).exists():
            m_path = config_path / m_path
        ext_dmcs, ext_res = load_csdb_manifest(m_path)
        if ext_dmcs or ext_res:
            available_dmcs.update(ext_dmcs)
            available_resources.update(ext_res)
            print(f"-> Loaded {len(ext_dmcs)} external DMCs and {len(ext_res)} resources from CSDB manifest.")

    # Audit discovered input BREX files (v8.7.1)
    if not args.no_brex and input_brex_files:
        print("Auditing input-discovered BREX files...")
        input_brex_errors = []
        for b in input_brex_files:
            errs = validate_brex_file(
                b,
                schema_dir=schema_dir,
                schema_mode=args.schema_mode,
                allowed_versions=allowed_versions_list,
                precompiled_elements=precompiled_els,
                precompiled_attributes=precompiled_attrs
            )
            if errs:
                print(f"[!] Rule Audit Violation in input BREX {Path(b).name}: {len(errs)} issues found.")
                for e in errs:
                    print(f"    - {e['message']}")
                    config_audit_errors.append({'file': Path(b).name, 'error': e})
                    input_brex_errors.append(e)
            brex_files.append({'path': b, 'is_config': False})

        # Abort if input BREX files contain blocking violations
        blocking_input_errors = [e for e in input_brex_errors if e.get('level', 0) >= abort_threshold]
        if blocking_input_errors:
            print(f"\n[FATAL] Input BREX Audit failed with {len(blocking_input_errors)} blocking issues.")
            sys.exit(1)

    if len(brex_files) == 0 and not args.no_brex:
        print("[!] Warning: No BREX files found. BREX engine will be idle.")
    if len(sch_files) == 0 and not args.no_sch:
        print("[!] Warning: No Schematron files found. Schematron engine will be idle.")

    # Engine Status Summary
    engines = []
    if not args.no_schema:
        engines.append("Schema")
    if not args.no_brex and brex_files:
        engines.append("BREX")
    if not args.no_sch and sch_files:
        engines.append("Schematron")
    if not args.no_integrity:
        engines.append("Integrity")
    print(f"Active Engines: {', '.join(engines) if engines else 'None'}")

    workers = args.max_workers or os.cpu_count() or 4
    dynamic_chunksize = max(1, min(50, total_files // (workers * 4)))
    print(f"Starting engine with {workers} processes (chunksize={dynamic_chunksize})...")

    init_data = {
        'args_dict': vars(args),
        'brex_list': brex_files,
        'sch_list': sch_files,
        'baseline_rules': baseline_rules,
        'available_dmcs': list(available_dmcs),
        'available_resources': list(available_resources)
    }

    # Reporting & Relational DB Init
    summary_data = {
        'total': 0, 'valid': 0, 'invalid': 0, 'warnings': 0,
        'by_schema': 0, 'by_naming': 0, 'by_brex': 0, 'by_schematron': 0,
        'by_resource': 0, 'by_reference': 0, 'by_config': 0,
        'by_syntax': 0
    }
    error_freq = Counter()
    final_logs = []
    valid_files, invalid_files = [], []

    # Initialize Local SQLite database (Relational)
    db_conn, summary_data['db_path'] = init_database(args.log_dir, run_timestamp)
    db_cursor = db_conn.cursor()
    error_cache = {}  # Cache Errors in-memory to prevent thousands of SELECTs

    # Live-log Config Audit Errors to DB (v8.7.0)
    if config_audit_errors:
        for audit in config_audit_errors:
            fname, e = audit['file'], audit['error']
            e_lvl = e.get('level', 40)
            if e_lvl >= 30:
                summary_data['by_config'] += 1
            c_lname = "ERROR" if e_lvl >= 40 else ("WARNING" if e_lvl >= 30 else "INFO")
            # Insert file record (for the BREX/Schematron file itself)
            dm_type = 'SCHEMATRON' if fname.endswith('.sch') else 'BREX'
            db_cursor.execute("INSERT INTO Files (timestamp, filename, dm_code, info_code, rpc, originator) "
                              "VALUES (?, ?, ?, ?, ?, ?)",
                              (datetime.now().strftime("%H:%M:%S"), fname, dm_type, 'Config', 'VALIDATOR', 'N/A'))
            file_id = db_cursor.lastrowid

            # Insert Error string
            msg = e['message']
            cache_key = ('Config', 'CONFIG_AUDIT', msg)
            if cache_key not in error_cache:
                db_cursor.execute("INSERT OR IGNORE INTO Errors (level, levelname, error_type, rule_id, message) "
                                  "VALUES (?, ?, ?, ?, ?)",
                                  (e_lvl, c_lname, 'Config', 'CONFIG_AUDIT', msg))
                db_cursor.execute("SELECT id FROM Errors WHERE error_type = ? AND rule_id = ? AND message = ?",
                                  cache_key)
                res_err = db_cursor.fetchone()
                if res_err:
                    error_cache[cache_key] = res_err[0]

            err_id = error_cache.get(cache_key)
            if err_id:
                db_cursor.execute("INSERT INTO Locations (file_id, error_id, line_number, xpath, attribute) "
                                  "VALUES (?, ?, ?, ?, ?)",
                                  (file_id, err_id, 'N/A', e.get('xpath', 'N/A'), 'N/A'))
        db_conn.commit()

    try:
        with multiprocessing.Pool(processes=workers,
                                  initializer=init_worker,
                                  initargs=(init_data,)) as pool:

            res_iterator = pool.imap_unordered(process_file, file_list, chunksize=dynamic_chunksize)
            p_start = time.time()

            # Streaming Process - Data is persisted immediately, never building a huge list
            for i, result in enumerate(res_iterator, 1):
                f_path, status, logs, file_info = result
                summary_data['total'] += 1
                name = Path(f_path).name

                if status['status'] == 'valid':
                    summary_data['valid'] += 1
                    valid_files.append(name)
                    if status.get('has_warnings'):
                        summary_data['warnings'] += 1
                else:
                    summary_data['invalid'] += 1
                    invalid_files.append(name)

                # Always update category distribution counters when findings exist
                if status.get('syntax'):
                    summary_data['by_syntax'] += 1
                if status.get('schema'):
                    summary_data['by_schema'] += 1
                if status.get('naming'):
                    summary_data['by_naming'] += 1
                if status.get('brex'):
                    summary_data['by_brex'] += 1
                if status.get('schematron'):
                    summary_data['by_schematron'] += 1
                if status.get('resource'):
                    summary_data['by_resource'] += 1
                if status.get('reference'):
                    summary_data['by_reference'] += 1

                if logs:
                    # Group errors by Rule ID using log objects for precision
                    for log in logs:
                        if log.get('level', 0) >= 20:  # INFO, WARNING, or ERROR
                            rule_id = log.get('rule_id', 'GENERIC')
                            if 'rule_stats' not in summary_data:
                                summary_data['rule_stats'] = {}
                            if rule_id not in summary_data['rule_stats']:
                                msg_clean = log['message'].split(' (Rule:')[0].split('] ')[-1][:100]
                                summary_data['rule_stats'][rule_id] = {'count': 0, 'files': set(), 'message': msg_clean}

                            summary_data['rule_stats'][rule_id]['count'] += 1
                            summary_data['rule_stats'][rule_id]['files'].add(name)

                    error_freq.update(status['errors'])

                # --- Live Database Streaming ---
                # 1. Insert Metadata to Files
                dm_c = file_info.get('dm_code', 'N/A')
                info_c = file_info.get('info_code', 'N/A')
                rpc_c = file_info.get('rpc', 'N/A')
                orig_c = file_info.get('originator', 'N/A')

                ts_now = datetime.now().strftime("%H:%M:%S")
                db_cursor.execute("INSERT INTO Files (timestamp, filename, dm_code, info_code, rpc, originator) "
                                  "VALUES (?, ?, ?, ?, ?, ?)",
                                  (ts_now, name, dm_c, info_c, rpc_c, orig_c))
                file_id = db_cursor.lastrowid

                # 2. Insert Strings to Errors & Link via Locations (persisting INFO, WARNING, and ERROR)
                loc_rows = []
                file_error_counts = Counter()
                for log in logs:
                    lvl = log.get('level', 0)
                    if lvl >= logging.INFO:
                        lname = "ERROR" if lvl >= logging.ERROR else ("WARNING" if lvl >= logging.WARNING else "INFO")
                        msg = log.get('message', '')
                        e_type = log.get('error_type', 'Unknown')

                        rule_id = log.get('rule_id', 'GENERIC')

                        # Dictionary Cache Check
                        cache_key = (e_type, rule_id, msg)
                        if cache_key not in error_cache:
                            db_cursor.execute("INSERT OR IGNORE INTO Errors (level, levelname, error_type, rule_id, "
                                              "message) VALUES (?, ?, ?, ?, ?)",
                                              (lvl, lname, e_type, rule_id, msg))
                            db_cursor.execute("SELECT id FROM Errors WHERE error_type = ? AND rule_id = ? "
                                              "AND message = ?", cache_key)
                            res_err = db_cursor.fetchone()
                            if res_err:
                                error_cache[cache_key] = res_err[0]

                        err_id = error_cache.get(cache_key)
                        if err_id:
                            # CASCADING ERROR BRAKE: Limit identical errors per file to 50
                            file_error_counts[err_id] += 1
                            if file_error_counts[err_id] <= 50:
                                loc_rows.append((file_id, err_id, log.get('location', 'N/A'), log.get('xpath', ''),
                                                 log.get('attribute', 'N/A')))
                            elif file_error_counts[err_id] == 51:
                                loc_rows.append((file_id, err_id, 'N/A',
                                                 '... [Additional identical occurrences SUPPRESSED]', 'N/A'))

                if loc_rows:
                    db_cursor.executemany("INSERT INTO Locations (file_id, error_id, line_number, xpath, attribute) "
                                          "VALUES (?, ?, ?, ?, ?)", loc_rows)

                # Commit periodically (WAL size control based on rows)
                if len(loc_rows) > 0 and (i % max(1, 10000 // max(len(loc_rows), 1))) == 0:
                    db_conn.commit()

                if i % 20 == 0 or i == total_files:
                    print_progress_bar(i, total_files, p_start, prefix='Processing', suffix='Complete')

            # Final DB Commit
            db_conn.commit()

    except KeyboardInterrupt:
        db_conn.commit()
        db_conn.close()
        print("\n[!] Interrupted by user. Exiting safely.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[FATAL] Pool Error: {e}")
        return

    # Reporting Phase
    print("\nProcessing complete. Aggregating results...")
    db_conn.close()

    summary_data.update({
        'top_errors': error_freq.most_common(50),
        'valid_files': valid_files,
        'invalid_files': invalid_files
    })

    if args.out_txt:
        print("-> Saving TXT lists...")
        write_text_reports(summary_data, run_timestamp, args.log_dir)

    if args.out_xml:
        print("-> Saving XML report...")
        write_xml_report(final_logs, summary_data, run_timestamp, args.log_dir)

    if getattr(args, 'out_junit', False):
        print("-> Saving JUnit XML report...")
        write_junit_report(summary_data, run_timestamp, args.log_dir)

    if getattr(args, 'out_sarif', False):
        print("-> Saving SARIF v2.1.0 report...")
        write_sarif_report(summary_data, run_timestamp, args.log_dir)

    if args.out_csv:
        print("-> Saving CSV export...")
        write_csv_report(run_timestamp, args.log_dir, summary_data['db_path'])

    if args.out_html:
        print("-> Saving HTML Dashboard...")
        write_html_report(final_logs, summary_data, run_timestamp, args.log_dir)

    duration = time.time() - start_time
    print(f"\nTime taken: {duration:.2f}s | Avg: {duration/total_files:.3f}s/file.")

    if summary_data['invalid'] > 0:
        print(f"\n[FAIL] Validation finished with {summary_data['invalid']} invalid files.")
        sys.exit(1)
    else:
        warn_cnt = summary_data.get('warnings', 0)
        if args.fail_on_warning and warn_cnt > 0:
            print(f"\n[FAIL] All files are valid, but {warn_cnt} files had warnings (--fail-on-warning).")
            sys.exit(1)
        if warn_cnt > 0:
            print(f"\n[SUCCESS] All files passed validation ({warn_cnt} files had non-blocking warnings)!")
        else:
            print("\n[SUCCESS] All files passed validation successfully!")
        sys.exit(0)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()

"""
S1000D Validator - Core Processing Logic (v8.6.1)

PURPOSE:
Core logic for XML validation, optimized for extreme performance on large batches (20k+ files).
Implements a Multi-Parser Hybrid Engine (Saxon + lxml) for max throughput.
"""

import os
import re
import logging
import hashlib
from typing import List, Dict, Any, Tuple
from pathlib import Path
from lxml import etree
from collections import defaultdict
import elementpath

from s1000d_validator.engines import IntegrityEngine, SaxonBrexEngine, SaxonSchematronEngine, Violation
from s1000d_validator.utils import (
    STANDARD_NAMESPACES,
    XSI_NS,
    parse_dmc_elements,
    extract_dm_metadata,
    extract_xsd_rule_id,
    extract_xpath_elements_and_attributes,
    find_lxml_element_for_saxon_node,
    resolve_schema_file,
    SchemaResolver,
    is_suppressed_violation
)
from s1000d_validator.audit import (
    validate_brex_file,
    validate_schematron_file
)

try:
    import saxonche
    HAS_SAXON = True
except ImportError:
    HAS_SAXON = False

# --- CONSTANTS ---
SVRL_NS = "http://purl.oclc.org/dsdl/svrl"

# --- GLOBAL WORKER STATE ---
GLOBAL_CONFIG: Dict[str, Any] = {}
GLOBAL_SCHEMAS: Dict[str, etree.XMLSchema] = {}
GLOBAL_BREX_RULES: Dict[str, List[Dict[str, str]]] = {}  # Map[ContextName, List[Rule]]
GLOBAL_BREX_CATALOG: Dict[str, Any] = {}  # Map[FileName, {ContextName, Rules}]
GLOBAL_SCHEMATRON_VALIDATORS: List[Dict[str, Any]] = []
GLOBAL_PARSER: Any = None
GLOBAL_VALIDATOR_PARSER: Any = None
GLOBAL_BASELINE_RULES: List[Dict[str, str]] = []
GLOBAL_SAXON_PROC: Any = None
GLOBAL_SAXON_BUILDER: Any = None
GLOBAL_SAXON_XP: Any = None
GLOBAL_DECLARED_NAMESPACES: Dict[str, str] = {}
GLOBAL_AVAILABLE_DMCS: set = set()
GLOBAL_AVAILABLE_RESOURCES: set = set()


def resolve_brex_from_catalog(ref_dmc_dict: Dict[str, Any]) -> str:
    if not ref_dmc_dict:
        return None
    candidates = []
    for key, entry in GLOBAL_BREX_CATALOG.items():
        if not isinstance(entry, dict) or 'dmc' not in entry:
            continue
        entry_dmc = entry['dmc']
        if entry_dmc.get('base_dmc') != ref_dmc_dict.get('base_dmc'):
            continue
        if ref_dmc_dict.get('issue_number') and entry_dmc.get('issue_number') != ref_dmc_dict['issue_number']:
            continue
        if ref_dmc_dict.get('language_iso') and entry_dmc.get('language_iso') != ref_dmc_dict['language_iso']:
            continue
        if ref_dmc_dict.get('country_iso') and entry_dmc.get('country_iso') != ref_dmc_dict['country_iso']:
            continue
        candidates.append((key, entry))

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0][0]

    def sort_key(cand):
        ent_dmc = cand[1]['dmc']
        issue_str = ent_dmc.get('issue_number', '000')
        in_work_str = ent_dmc.get('in_work', '00')
        try:
            issue_val = int(issue_str)
        except ValueError:
            issue_val = 0
        try:
            in_work_val = int(in_work_str)
        except ValueError:
            in_work_val = 0
        return (issue_val, in_work_val)

    candidates.sort(key=sort_key, reverse=True)
    return candidates[0][0]


def init_worker(init_data: Dict[str, Any]) -> None:
    """Initializes worker and loads all rules/schemas into memory once."""
    global GLOBAL_CONFIG, GLOBAL_SCHEMAS, GLOBAL_BREX_RULES, GLOBAL_BREX_CATALOG, GLOBAL_SCHEMATRON_VALIDATORS
    global GLOBAL_PARSER, GLOBAL_VALIDATOR_PARSER, GLOBAL_BASELINE_RULES, GLOBAL_SAXON_PROC, GLOBAL_SAXON_BUILDER
    global GLOBAL_SAXON_XP, GLOBAL_DECLARED_NAMESPACES, GLOBAL_AVAILABLE_DMCS, GLOBAL_AVAILABLE_RESOURCES

    # Silence worker logging
    logging.basicConfig(level=logging.CRITICAL + 1)

    GLOBAL_BREX_RULES = defaultdict(list)
    GLOBAL_BREX_CATALOG = {}
    GLOBAL_DECLARED_NAMESPACES = {}
    GLOBAL_BASELINE_RULES = []
    GLOBAL_CONFIG = init_data.get('args_dict', {})
    GLOBAL_BASELINE_RULES = init_data.get('baseline_rules', [])
    GLOBAL_AVAILABLE_DMCS = set(init_data.get('available_dmcs', []))
    GLOBAL_AVAILABLE_RESOURCES = set(init_data.get('available_resources', []))

    # Initialize cached parser
    GLOBAL_PARSER = etree.XMLParser(recover=True, load_dtd=False, no_network=True)
    GLOBAL_VALIDATOR_PARSER = etree.XMLParser(recover=False, load_dtd=False, no_network=True)

    # 1. Cache XSD Schemas (Performance Boost)
    cfg_schema_dir = GLOBAL_CONFIG.get('schema_dir')
    cfg_config_dir = GLOBAL_CONFIG.get('config_dir')
    if cfg_schema_dir:
        schema_dir = Path(cfg_schema_dir)
    elif cfg_config_dir:
        schema_dir = Path(cfg_config_dir) / "schemas"
    else:
        schema_dir = Path("config/schemas")

    # Register custom SchemaResolver to handle structured/flat relative lookup
    schema_mode = GLOBAL_CONFIG.get('schema_mode', 'auto')
    resolver = SchemaResolver(schema_dir, schema_mode=schema_mode)
    GLOBAL_PARSER.resolvers.add(resolver)
    GLOBAL_VALIDATOR_PARSER.resolvers.add(resolver)

    if schema_dir.is_dir():
        for xsd in schema_dir.rglob("*.xsd"):
            try:
                s_key = str(xsd.resolve())
                GLOBAL_SCHEMAS[s_key] = etree.XMLSchema(etree.parse(str(xsd), parser=GLOBAL_PARSER))
                # Also cache by name as a fallback key
                GLOBAL_SCHEMAS[xsd.name] = GLOBAL_SCHEMAS[s_key]
            except Exception as e:
                logging.warning(f"Failed to load XSD {xsd.name}: {e}")

    # 2. Cache BREX Rules
    for brex_info in init_data.get('brex_list', []):
        try:
            if isinstance(brex_info, dict):
                b_path = brex_info['path']
                is_config = brex_info.get('is_config', True)
            else:
                b_path = brex_info
                is_config = True
            b_name = Path(b_path).name
            tree = etree.parse(str(b_path), parser=GLOBAL_PARSER)

            # Extract own DMC and parent BREX reference
            own_dmc_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmAddress']"
                                    "//*[local-name()='dmCode']")
            own_issue_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmAddress']"
                                      "//*[local-name()='issueInfo']")
            own_lang_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmAddress']"
                                     "//*[local-name()='language']")

            own_dmc_dict = parse_dmc_elements(own_dmc_el[0] if own_dmc_el else None,
                                              own_issue_el[0] if own_issue_el else None,
                                              own_lang_el[0] if own_lang_el else None)
            if not own_dmc_dict or not own_dmc_dict.get('base_dmc'):
                own_dmc_dict = {'base_dmc': b_name.lower()}

            parent_dmc_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmStatus']"
                                       "//*[local-name()='brexDmRef']//*[local-name()='dmCode']")
            parent_issue_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmStatus']"
                                         "//*[local-name()='brexDmRef']//*[local-name()='issueInfo']")
            parent_lang_el = tree.xpath("//*[local-name()='identAndStatusSection']//*[local-name()='dmStatus']"
                                        "//*[local-name()='brexDmRef']//*[local-name()='language']")

            parent_ref_dict = None
            if parent_dmc_el:
                parent_ref_dict = parse_dmc_elements(parent_dmc_el[0] if parent_dmc_el else None,
                                                     parent_issue_el[0] if parent_issue_el else None,
                                                     parent_lang_el[0] if parent_lang_el else None)

            # Catalog for chain searching
            GLOBAL_BREX_CATALOG[b_name] = {
                'rules': defaultdict(list),
                'notation_rules': [],
                'dmc': own_dmc_dict,
                'parent_ref': parent_ref_dict,
                'is_config': is_config
            }

            # Parse notationRuleList if present (REQ-303)
            for n_rule in tree.xpath("//*[local-name()='notationRule']"):
                n_els = n_rule.xpath(".//*[local-name()='notationName']")
                u_els = n_rule.xpath(".//*[local-name()='objectUse']")
                n_el = n_els[0] if n_els else None
                u_el = u_els[0] if u_els else None
                if n_el is not None and (n_el.text or "").strip():
                    n_name = n_el.text.strip()
                    n_flag = (n_el.get("allowedNotationFlag") or "1").strip()
                    n_msg = (u_el.text or f"Notation '{n_name}' violates BREX notationRule").strip() if u_el is not None else f"Notation '{n_name}' violates BREX notationRule"
                    n_id = n_rule.get("id") or f"BRX-NOT-{n_name.upper()}"
                    GLOBAL_BREX_CATALOG[b_name]['notation_rules'].append({
                        "id": n_id,
                        "notation_name": n_name,
                        "flag": n_flag,
                        "message": n_msg,
                        "source_brex": b_name
                    })

            for group in tree.xpath("//*[local-name()='contextRules']"):
                ctx = group.get("rulesContext", "")
                # Better Context Detection (v8.7.0 - supports .xsd paths and S1000D URNs)
                match = re.search(r'([^/]+)\.xsd', ctx)
                if match:
                    key = match.group(1).lower()
                elif ctx.strip().lower().startswith("urn:"):
                    urn_match = re.search(r':([a-zA-Z0-9_-]+)$', ctx.strip())
                    key = urn_match.group(1).lower() if urn_match else "general"
                else:
                    key = "general"

                if GLOBAL_CONFIG.get('debug'):
                    print(f"      [DEBUG] Loading BREX Context '{key}' -> "
                          f"{len(group.xpath('.//*[local-name()=\"structureObjectRule\"]'))} rules")

                for rule in group.xpath(".//*[local-name()='structureObjectRule']"):
                    p_els = rule.xpath(".//*[local-name()='objectPath']")
                    u_els = rule.xpath(".//*[local-name()='objectUse']")
                    p_el = p_els[0] if p_els else None
                    u_el = u_els[0] if u_els else None
                    if p_el is not None and u_el is not None:
                        flag = (p_el.get("allowedObjectFlag") or "2").strip()
                        if flag in ["2", "0", "1"]:
                            q_str = (p_el.text or "").strip()

                            rule_id = rule.get("id")
                            msg = (u_el.text or "").strip()
                            if not rule_id or rule_id == "GENERIC":
                                br_match = re.search(r'BRDP-[a-zA-Z0-9-]+', msg)
                                if br_match:
                                    rule_id = br_match.group(0)
                                else:
                                    h = hashlib.md5(q_str.encode()).hexdigest()[:8].upper()
                                    rule_id = f"BRX-{h}"

                            try:
                                # Use rulesContext as default namespace if it's a URI
                                def_ns = ctx if ctx.strip().startswith("http") else None
                                selector = elementpath.Selector(q_str, default_namespace=def_ns,
                                                                namespaces=STANDARD_NAMESPACES)

                                lxml_selector = None
                                xp2_funcs = ["matches(", "lower-case(", "upper-case(", "replace(",
                                             "tokenize(", "ends-with("]
                                if not any(f in q_str for f in xp2_funcs):
                                    try:
                                        lxml_selector = etree.XPath(q_str)
                                    except Exception:
                                        pass
                            except Exception:
                                continue

                            rule_data = {
                                "id": rule_id, "query": q_str, "selector": selector,
                                "lxml_selector": lxml_selector, "flag": flag, "message": msg,
                                "source_brex": b_name
                            }

                            if flag in ["1", "2"]:
                                v_allowed, v_not_allowed, v_patterns, v_ranges = [], [], [], []
                                for v in rule.xpath(".//*[local-name()='objectValue']"):
                                    f = (v.get("valueForm") or "single").strip()
                                    allowed = (v.get("valueAllowed") or "").strip()
                                    not_allowed = (v.get("valueNotAllowed") or "").strip()

                                    if f == "single":
                                        if allowed:
                                            v_allowed.append(allowed)
                                        if not_allowed:
                                            v_not_allowed.append(not_allowed)
                                    elif f == "pattern":
                                        try:
                                            v_patterns.append({
                                                'pattern': re.compile(allowed or not_allowed),
                                                'allowed': bool(allowed)
                                            })
                                        except Exception:
                                            pass
                                    elif f == "range":
                                        r_val = allowed or not_allowed
                                        if r_val and "~" in r_val:
                                            v_ranges.append({
                                                'range': r_val.split("~"),
                                                'allowed': bool(allowed)
                                            })

                                rule_data.update({
                                    "v_allowed": v_allowed, "v_not_allowed": v_not_allowed,
                                    "v_patterns": v_patterns, "v_ranges": v_ranges,
                                    "fallback_tags": list(reversed(re.findall(r'(?:/|//|\.)([a-zA-Z0-9_:-]+)(?!\()',
                                                                   q_str)))
                                })

                            # Extract sub-attributes for "flag 0" deep inspection
                            if flag == "0" and "@" in q_str:
                                rule_data['sub_attrs'] = [a.strip() for a in re.findall(r'@([a-zA-Z0-9_:-]+)', q_str)]

                            GLOBAL_BREX_CATALOG[b_name]['rules'][key].append(rule_data)
                            # Mode 'project' uses all rules combined
                            GLOBAL_BREX_RULES[key].append(rule_data)

        except Exception as e:
            logging.error(f"Failed to process BREX file {b_path}: {e}")

    if HAS_SAXON:
        try:
            GLOBAL_SAXON_PROC = saxonche.PySaxonProcessor(license=False)
            GLOBAL_SAXON_BUILDER = GLOBAL_SAXON_PROC.new_document_builder()
            GLOBAL_SAXON_XP = GLOBAL_SAXON_PROC.new_xpath_processor()
            GLOBAL_SAXON_XP.set_caching(True)
        except Exception as e:
            logging.error(f"Failed to initialize Saxon XSLT environment: {e}")

    # 3. Cache Schematron
    sch_list = init_data.get('sch_list', [])
    if sch_list and HAS_SAXON and GLOBAL_SAXON_PROC:
        try:
            xslt_proc = GLOBAL_SAXON_PROC.new_xslt30_processor()

            schxslt_dir = Path(GLOBAL_CONFIG.get('config_dir', '')) / 'schxslt' \
                if GLOBAL_CONFIG.get('config_dir') else Path('config/schxslt')
            p_inc = xslt_proc.compile_stylesheet(stylesheet_file=str(schxslt_dir / "iso_dsdl_include.xsl"))
            p_exp = xslt_proc.compile_stylesheet(stylesheet_file=str(schxslt_dir / "iso_abstract_expand.xsl"))
            p_svrl = xslt_proc.compile_stylesheet(stylesheet_file=str(schxslt_dir / "iso_svrl_for_xslt2.xsl"))

            for s_path in sch_list:
                try:
                    # Execute the 3-Step compilation
                    sch_node = GLOBAL_SAXON_BUILDER.parse_xml(xml_file_name=str(s_path))

                    s1_node = GLOBAL_SAXON_BUILDER.parse_xml(xml_text=p_inc.transform_to_string(xdm_node=sch_node))
                    s2_node = GLOBAL_SAXON_BUILDER.parse_xml(xml_text=p_exp.transform_to_string(xdm_node=s1_node))
                    val_str = p_svrl.transform_to_string(xdm_node=s2_node)

                    GLOBAL_SCHEMATRON_VALIDATORS.append({
                        'name': Path(s_path).name,
                        'validator': xslt_proc.compile_stylesheet(stylesheet_text=val_str)
                    })
                except Exception as e:
                    logging.error(f"Failed to compile Schematron {s_path}: {e}")
        except Exception as e:
            logging.error(f"Failed to initialize Saxon XSLT for Schematron: {e}")
    elif sch_list and not HAS_SAXON:
        logging.error("Schematron files provided, but 'saxonche' is not installed. Schematron validation skipped.")


def log_to_list(log_list: List[Dict], level: int, message: str, file_info: Dict, **kwargs) -> None:
    log_list.append({
        'level': level, 'message': message, 'filename': file_info.get('filename', 'N/A'),
        'dm_code': file_info.get('dm_code', 'N/A'), 'info_code': file_info.get('info_code', 'N/A'),
        'rpc': file_info.get('rpc', 'N/A'), 'originator': file_info.get('originator', 'N/A'),
        'schema_location': file_info.get('schema_location', 'N/A'),
        'error_type': kwargs.get('error_type', 'N/A'), 'rule_id': kwargs.get('rule_id', 'GENERIC'),
        'location': kwargs.get('location', 'N/A'), 'xpath': kwargs.get('xpath', 'N/A'),
        'attribute': kwargs.get('attribute', 'N/A')
    })


def is_suppressed(error_type: str, file_info: Dict, message: str, xpath: str, rule_id: str = "") -> bool:
    """Checks if an error matches any active baseline suppression rule."""
    return is_suppressed_violation(
        error_type,
        rule_id,
        file_info.get('dm_code', ''),
        xpath,
        message,
        GLOBAL_BASELINE_RULES
    )


def get_starting_brex_key(file_info: Dict[str, Any], filename: str) -> str:
    """Resolves the initial BREX file key using mapping or file metadata."""
    mappings = GLOBAL_CONFIG.get('brex_mappings', {})
    mapped_brex = None
    if mappings:
        fname_upper = filename.upper()
        # Sort keys by length descending to match most specific prefix first
        sorted_keys = sorted([k for k in mappings.keys() if k != '*'], key=len, reverse=True)
        for key in sorted_keys:
            if fname_upper.startswith(key.upper()):
                mapped_brex = mappings[key]
                break
        if not mapped_brex and '*' in mappings:
            mapped_brex = mappings['*']

    curr_brex_key = None
    if mapped_brex:
        mapped_brex_lower = mapped_brex.lower()
        for k in GLOBAL_BREX_CATALOG.keys():
            if k.lower() == mapped_brex_lower:
                curr_brex_key = k
                break
        # Fallback search if not direct match
        if not curr_brex_key:
            for k, entry in GLOBAL_BREX_CATALOG.items():
                b_dmc = entry['dmc'].get('base_dmc', '').lower()
                if b_dmc == mapped_brex_lower.replace(".xml", "") or mapped_brex_lower in k.lower():
                    curr_brex_key = k
                    break

    if not curr_brex_key:
        ref_detail = file_info.get('brex_ref_detail')
        curr_brex_key = resolve_brex_from_catalog(ref_detail)
        if not curr_brex_key and file_info.get('brex_ref'):
            legacy_ref = file_info.get('brex_ref').lower().replace(".xml", "")
            candidates = []
            for k, entry in GLOBAL_BREX_CATALOG.items():
                if not isinstance(entry, dict) or 'dmc' not in entry:
                    continue
                b_dmc = entry['dmc'].get('base_dmc', '').lower()
                if b_dmc == legacy_ref or legacy_ref in b_dmc or legacy_ref in k.lower():
                    candidates.append((k, entry))
            if candidates:
                def sort_key(cand):
                    ent_dmc = cand[1]['dmc']
                    issue_str = ent_dmc.get('issue_number', '000')
                    in_work_str = ent_dmc.get('in_work', '00')
                    try:
                        issue_val = int(issue_str)
                    except ValueError:
                        issue_val = 0
                    try:
                        in_work_val = int(in_work_str)
                    except ValueError:
                        in_work_val = 0
                    return (issue_val, in_work_val)
                candidates.sort(key=sort_key, reverse=True)
                curr_brex_key = candidates[0][0]

    return curr_brex_key


def _mark_violation_status(status: Dict[str, Any], category_key: str, level: int) -> None:
    """Track findings without coupling file validity to the batch exit policy."""
    status[category_key] = True
    if level >= 40:
        status['status'] = 'invalid'
    elif level >= 30:
        status['has_warnings'] = True


def process_file(file_path: str) -> Tuple[str, Dict[str, Any], List[Dict]]:
    """The main validation loop executed for every file."""
    p_path = Path(file_path)
    file_info = {'filename': p_path.name, 'dm_code': 'N/A', 'info_code': 'N/A', 'rpc': 'N/A', 'originator': 'N/A',
                 'schema_location': 'N/A'}
    log_list, status = [], {'status': 'valid', 'has_warnings': False, 'schema': False, 'naming': False,
                            'brex': False, 'schematron': False, 'errors': []}

    try:
        # Step 1: Parse using cached lxml parser (needed for XSD/Schematron/Metadata)
        tree_doc = etree.parse(str(p_path), GLOBAL_VALIDATOR_PARSER)
        tree = tree_doc.getroot()
        extract_dm_metadata(tree, file_info)
        ns, root_tag = tree.nsmap, etree.QName(tree.tag).localname

        # Step 1b: Parse using Saxon for extreme performance (XPath 3.1) only when BREX or Schematron is active
        saxon_xp, saxon_doc = None, None
        need_saxon = (
            (not GLOBAL_CONFIG.get('no_brex', False) and bool(GLOBAL_BREX_CATALOG)) or
            (not GLOBAL_CONFIG.get('no_sch', False) and bool(GLOBAL_SCHEMATRON_VALIDATORS))
        )
        if HAS_SAXON and need_saxon and GLOBAL_SAXON_BUILDER and GLOBAL_CONFIG.get('validation_enabled', True) \
           and GLOBAL_SAXON_XP is not None:
            try:
                GLOBAL_SAXON_BUILDER.set_line_numbering(True)
                saxon_doc = GLOBAL_SAXON_BUILDER.parse_xml(xml_file_name=str(p_path))
                saxon_xp = GLOBAL_SAXON_XP
                saxon_xp.set_context(xdm_item=saxon_doc)
                # S1000D Namespace Synchronization
                # Handle default namespace to prevent stale bindings
                default_uri = ns.get(None)
                if default_uri:
                    if GLOBAL_DECLARED_NAMESPACES.get('') != default_uri:
                        try:
                            saxon_xp.declare_namespace(prefix='', uri=default_uri)
                            GLOBAL_DECLARED_NAMESPACES[''] = default_uri
                        except Exception:
                            pass
                else:
                    if GLOBAL_DECLARED_NAMESPACES.get('') != '':
                        try:
                            saxon_xp.declare_namespace(prefix='', uri='')
                            GLOBAL_DECLARED_NAMESPACES[''] = ''
                        except Exception:
                            pass

                # Handle prefixed namespaces
                for prefix, uri in ns.items():
                    if prefix is not None:
                        if GLOBAL_DECLARED_NAMESPACES.get(prefix) != uri:
                            try:
                                saxon_xp.declare_namespace(prefix=prefix, uri=uri)
                                GLOBAL_DECLARED_NAMESPACES[prefix] = uri
                            except Exception:
                                pass
            except Exception:
                pass

        # Naming Check
        if file_info['dm_code'] != 'N/A':
            name_match = re.match(r"^(?:DMC|PMC|DMLC)-(.*?)_.*?\..*$", p_path.name, re.I)
            if name_match:
                name_code = name_match.group(1).upper().replace("_", "-")
                if name_code != file_info['dm_code'].upper():
                    msg = f"Naming Mismatch: Filename '{name_code}' vs Content '{file_info['dm_code'].upper()}'"
                    if not is_suppressed("Naming", file_info, msg, "", rule_id="dm-integrity"):
                        _mark_violation_status(status, 'naming', 40)
                        status['errors'].append(msg)
                        log_to_list(log_list, 40, msg, file_info, error_type="Naming", rule_id="dm-integrity")

        # XSD Validation using cached/resolved Schemas
        if GLOBAL_CONFIG.get('validation_enabled', True) and not GLOBAL_CONFIG.get('no_schema', False):
            # Resolve schema directory
            cfg_schema_dir = GLOBAL_CONFIG.get('schema_dir')
            cfg_config_dir = GLOBAL_CONFIG.get('config_dir')
            if cfg_schema_dir:
                schema_dir = Path(cfg_schema_dir)
            elif cfg_config_dir:
                schema_dir = Path(cfg_config_dir) / "schemas"
            else:
                schema_dir = Path("config/schemas")

            schema_mode = GLOBAL_CONFIG.get('schema_mode', 'auto')
            allowed_versions = GLOBAL_CONFIG.get('allowed_versions')

            sloc = file_info.get('schema_location_raw')
            schema_path = None
            if sloc:
                schema_path = resolve_schema_file(sloc, schema_dir, xml_file_path=p_path, schema_mode=schema_mode)

            # Check S1000D Version compliance if configured
            if allowed_versions:
                detected_version = None
                if sloc:
                    version_match = re.search(r'S1000D_([0-9]+)[-_.]([0-9]+)', sloc, re.I)
                    if version_match:
                        detected_version = f"{version_match.group(1)}.{version_match.group(2)}"
                if not detected_version and schema_path:
                    version_match = re.search(r'S1000D_([0-9]+)[-_.]([0-9]+)', str(schema_path), re.I)
                    if version_match:
                        detected_version = f"{version_match.group(1)}.{version_match.group(2)}"

                if detected_version and detected_version not in allowed_versions:
                    msg = f"Version Violation: File references S1000D version '{detected_version}', " \
                          f"which is not allowed. Allowed versions: {', '.join(allowed_versions)}."
                    if not is_suppressed("Schema", file_info, msg, "", rule_id="S1000D_VERSION_VIOLATION"):
                        _mark_violation_status(status, 'schema', 40)
                        status['errors'].append(msg)
                        log_to_list(log_list, 40, msg, file_info, error_type="Schema",
                                    rule_id="S1000D_VERSION_VIOLATION", location="Line 2",
                                    attribute=sloc or "N/A")

            # Perform XSD schema validation
            s_key = None
            if schema_path:
                s_key = str(schema_path.resolve())
            elif file_info.get('schema_location') in GLOBAL_SCHEMAS:
                s_key = file_info['schema_location']
            elif f"{root_tag}.xsd" in GLOBAL_SCHEMAS:
                s_key = f"{root_tag}.xsd"

            if s_key:
                # Compile schema dynamically if not cached in GLOBAL_SCHEMAS
                if s_key not in GLOBAL_SCHEMAS:
                    try:
                        GLOBAL_SCHEMAS[s_key] = etree.XMLSchema(etree.parse(s_key, parser=GLOBAL_PARSER))
                    except Exception as e:
                        logging.warning(f"Failed to compile schema {s_key}: {e}")

                if s_key in GLOBAL_SCHEMAS:
                    try:
                        GLOBAL_SCHEMAS[s_key].assertValid(tree)
                    except etree.DocumentInvalid as e:
                        # Determine severity from config
                        sev_map = {"ERROR": 40, "WARNING": 30, "INFO": 20}
                        secondary_sev_name = GLOBAL_CONFIG.get("schema_severity", "ERROR").upper()
                        sev_level = sev_map.get(secondary_sev_name, 40)
                        for err in e.error_log:
                            xsd_rule_id = extract_xsd_rule_id(err.message)
                            if not is_suppressed("Schema", file_info, err.message, "", rule_id=xsd_rule_id):
                                _mark_violation_status(status, 'schema', sev_level)
                                status['errors'].append(err.message)
                                log_to_list(log_list, sev_level, "XML Schema Violation", file_info,
                                            error_type="Schema", rule_id=xsd_rule_id,
                                            location=f"Line {err.line}", attribute=err.message)

        # Step 2: Rules Engine (BREX)
        if GLOBAL_CONFIG.get('validation_enabled', True) and not GLOBAL_CONFIG.get('no_brex', False):
            brex_mode = GLOBAL_CONFIG.get('brex_mode', 'project')
            rules_to_apply = []

            if brex_mode == 'project':
                # Map schema location to context key
                s_key = (file_info.get('schema_location') or "").lower().replace(".xsd", "")

                # 1. Trace reference chain
                seen_in_chain = set()
                curr_brex_key = get_starting_brex_key(file_info, p_path.name)
                while curr_brex_key and curr_brex_key not in seen_in_chain:
                    seen_in_chain.add(curr_brex_key)
                    cat_entry = GLOBAL_BREX_CATALOG.get(curr_brex_key)
                    if cat_entry:
                        parent_ref = cat_entry.get('parent_ref')
                        curr_brex_key = resolve_brex_from_catalog(parent_ref)
                        if not curr_brex_key and parent_ref and parent_ref.get('base_dmc'):
                            legacy_parent_ref = parent_ref.get('base_dmc').lower()
                            candidates = []
                            for k, entry in GLOBAL_BREX_CATALOG.items():
                                if not isinstance(entry, dict) or 'dmc' not in entry:
                                    continue
                                b_dmc = entry['dmc'].get('base_dmc', '').lower()
                                if b_dmc == legacy_parent_ref or legacy_parent_ref in b_dmc or legacy_parent_ref in k.lower():
                                    candidates.append((k, entry))
                            if candidates:
                                def sort_key(cand):
                                    ent_dmc = cand[1]['dmc']
                                    issue_str = ent_dmc.get('issue_number', '000')
                                    in_work_str = ent_dmc.get('in_work', '00')
                                    try:
                                        issue_val = int(issue_str)
                                    except ValueError:
                                        issue_val = 0
                                    try:
                                        in_work_val = int(in_work_str)
                                    except ValueError:
                                        in_work_val = 0
                                    return (issue_val, in_work_val)
                                candidates.sort(key=sort_key, reverse=True)
                                curr_brex_key = candidates[0][0]
                    else:
                        break

                # 2. Gather the rules from only the resolved BREX files in the chain that reside in the config folder
                resolved_brex_keys = [k for k in seen_in_chain if GLOBAL_BREX_CATALOG.get(k, {}).get('is_config', True)]
                if not resolved_brex_keys:
                    resolved_brex_keys = [k for k, entry in GLOBAL_BREX_CATALOG.items() if entry.get('is_config', True)]
                
                rules_to_apply = []
                notation_rules_to_apply = []
                for r_key in resolved_brex_keys:
                    cat_entry = GLOBAL_BREX_CATALOG.get(r_key)
                    if cat_entry:
                        rules = cat_entry['rules']
                        rules_to_apply.extend(rules.get(s_key, []) +
                                              rules.get(root_tag, []) +
                                              rules.get('general', []))
                        notation_rules_to_apply.extend(cat_entry.get('notation_rules', []))
            else:
                # Chain Mode: Walk the BREX references
                seen_brex = set()
                notation_rules_to_apply = []

                # Resolve using mappings or reference
                curr_brex_key = get_starting_brex_key(file_info, p_path.name)

                # If we still can't find it and mode is 'chain', raise a violation
                if not curr_brex_key and brex_mode == 'chain':
                    ref_name = file_info.get('brex_ref') or "Unknown"
                    msg = f"Missing BREX reference: BREX module '{ref_name}' could not be resolved " \
                          f"from the config directory."
                    if not is_suppressed("BREX", file_info, msg, "", rule_id="BREX_MISSING"):
                        _mark_violation_status(status, 'brex', 40)
                        status['errors'].append(msg)
                        log_to_list(log_list, 40, msg, file_info, error_type="BREX", rule_id="BREX_MISSING")

                while curr_brex_key and curr_brex_key not in seen_brex:
                    seen_brex.add(curr_brex_key)
                    cat_entry = GLOBAL_BREX_CATALOG.get(curr_brex_key)
                    if cat_entry:
                        rules = cat_entry['rules']
                        s_key = (file_info.get('schema_location') or "").lower().replace(".xsd", "")
                        rules_to_apply.extend(rules.get(s_key, []) +
                                              rules.get(root_tag, []) +
                                              rules.get('general', []))
                        notation_rules_to_apply.extend(cat_entry.get('notation_rules', []))

                        # Move to the parent BREX reference
                        parent_ref = cat_entry.get('parent_ref')
                        curr_brex_key = resolve_brex_from_catalog(parent_ref)

                        # Fallback for parent_ref lookup if resolve failed but parent_ref exists
                        if not curr_brex_key and parent_ref and parent_ref.get('base_dmc'):
                            legacy_parent_ref = parent_ref.get('base_dmc').lower()
                            candidates = []
                            for k, entry in GLOBAL_BREX_CATALOG.items():
                                if not isinstance(entry, dict) or 'dmc' not in entry:
                                    continue
                                b_dmc = entry['dmc'].get('base_dmc', '').lower()
                                if b_dmc == legacy_parent_ref or legacy_parent_ref in b_dmc or legacy_parent_ref in k.lower():
                                    candidates.append((k, entry))
                            if candidates:
                                def sort_key(cand):
                                    ent_dmc = cand[1]['dmc']
                                    issue_str = ent_dmc.get('issue_number', '000')
                                    in_work_str = ent_dmc.get('in_work', '00')
                                    try:
                                        issue_val = int(issue_str)
                                    except ValueError:
                                        issue_val = 0
                                    try:
                                        in_work_val = int(in_work_str)
                                    except ValueError:
                                        in_work_val = 0
                                    return (issue_val, in_work_val)
                                candidates.sort(key=sort_key, reverse=True)
                                curr_brex_key = candidates[0][0]

                        # If a parent reference is specified but could not be resolved, and mode is 'chain'
                        if not curr_brex_key and parent_ref and brex_mode == 'chain':
                            p_ref_name = parent_ref.get('base_dmc', 'Unknown') + ".xml"
                            msg = f"Missing parent BREX reference: BREX module '{p_ref_name}' could not " \
                                  f"be resolved from the config directory."
                            if not is_suppressed("BREX", file_info, msg, "", rule_id="BREX_MISSING"):
                                _mark_violation_status(status, 'brex', 40)
                                status['errors'].append(msg)
                                log_to_list(log_list, 40, msg, file_info, error_type="BREX",
                                            rule_id="BREX_MISSING")
                    else:
                        break

                if not rules_to_apply:
                    s_key = (file_info.get('schema_location') or "").lower().replace(".xsd", "")
                    fallback_keys = [k for k, entry in GLOBAL_BREX_CATALOG.items() if entry.get('is_config', True)]
                    for r_key in fallback_keys:
                        cat_entry = GLOBAL_BREX_CATALOG.get(r_key)
                        if cat_entry:
                            rules = cat_entry['rules']
                            rules_to_apply.extend(rules.get(s_key, []) +
                                                  rules.get(root_tag, []) +
                                                  rules.get('general', []))
                            notation_rules_to_apply.extend(cat_entry.get('notation_rules', []))

            if rules_to_apply and GLOBAL_CONFIG.get('debug'):
                print(f"   [DEBUG] Applying {len(rules_to_apply)} BREX rules to {file_info['filename']}")

            if rules_to_apply or notation_rules_to_apply:
                brex_engine = SaxonBrexEngine(GLOBAL_CONFIG)
                v_list = brex_engine.run(tree, tree_doc, file_info,
                                         rules=rules_to_apply,
                                         notation_rules=notation_rules_to_apply,
                                         saxon_xp=saxon_xp,
                                         ns=ns,
                                         baseline_rules=GLOBAL_BASELINE_RULES)

                hit_count = 0
                for v in v_list:
                    hit_count += 1
                    _mark_violation_status(status, 'brex', v.level)
                    status['errors'].append(v.message)
                    log_list.append(v.to_dict(file_info))

                if hit_count > 0 and GLOBAL_CONFIG.get('debug'):
                    print(f"      [DEBUG] Found {hit_count} BREX violations in {file_info['filename']}")

        # Step 3: Schematron Engine (v8.7.0)
        if GLOBAL_SCHEMATRON_VALIDATORS and GLOBAL_SAXON_BUILDER and GLOBAL_CONFIG.get('validation_enabled', True) \
           and not GLOBAL_CONFIG.get('no_sch', False):
            try:
                if not saxon_doc:
                    GLOBAL_SAXON_BUILDER.set_line_numbering(True)
                    saxon_doc = GLOBAL_SAXON_BUILDER.parse_xml(xml_file_name=str(p_path))

                sch_engine = SaxonSchematronEngine(GLOBAL_CONFIG)
                v_list = sch_engine.run(tree, tree_doc, file_info,
                                        validators=GLOBAL_SCHEMATRON_VALIDATORS,
                                        saxon_doc=saxon_doc,
                                        ns=ns,
                                        baseline_rules=GLOBAL_BASELINE_RULES)

                for v in v_list:
                    _mark_violation_status(status, 'schematron', v.level)
                    status['errors'].append(v.message)
                    log_list.append(v.to_dict(file_info))
            except Exception as e:
                logging.error(f"Schematron Runtime error for {file_info['filename']}: {e}")

        # Step 4: Reference Integrity & Resource Verification (Broken Link Check)
        if GLOBAL_CONFIG.get('validation_enabled', True) and not GLOBAL_CONFIG.get('no_integrity', False):
            int_engine = IntegrityEngine(GLOBAL_CONFIG)
            v_list = int_engine.run(tree, tree_doc, file_info,
                                    available_dmcs=GLOBAL_AVAILABLE_DMCS,
                                    available_resources=GLOBAL_AVAILABLE_RESOURCES,
                                    baseline_rules=GLOBAL_BASELINE_RULES)

            for v in v_list:
                _mark_violation_status(status, v.error_type.lower(), v.level)
                status['errors'].append(f"{v.error_type}: {v.message}")
                log_list.append(v.to_dict(file_info))

    except KeyboardInterrupt:
        raise
    except etree.XMLSyntaxError as e:
        _mark_violation_status(status, 'syntax', 40)
        status['errors'].append(str(e))
        log_to_list(log_list, 40, f"XML Syntax Error: {e}", file_info, error_type="Syntax",
                    rule_id="XML_SYNTAX_ERROR",
                    location=f"Line {e.lineno}" if hasattr(e, 'lineno') else "N/A")
    except Exception as e:
        log_to_list(log_list, 40, f"Fatal: {e}", file_info)
        _mark_violation_status(status, 'schema', 40)
        status['errors'].append(str(e))

    return file_path, status, log_list, file_info

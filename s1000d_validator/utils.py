import re
from typing import Dict, Any, Tuple
from pathlib import Path
from lxml import etree

XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"

STANDARD_NAMESPACES = {
    'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
    'xml': 'http://www.w3.org/XML/1998/namespace',
    'xlink': 'http://www.w3.org/1999/xlink',
    'rdf': 'http://www.w3.org/1999/02/22-rdf-syntax-ns#',
    'dc': 'http://purl.org/dc/elements/1.1/'
}

XPATH_KEYWORDS = {
    'and', 'or', 'not', 'true', 'false', 'mod', 'div',
    'starts-with', 'contains', 'substring', 'substring-before', 'substring-after',
    'string-length', 'normalize-space', 'translate', 'concat', 'string',
    'local-name', 'namespace-uri', 'name', 'count', 'sum', 'avg', 'min', 'max',
    'position', 'last', 'number', 'boolean', 'round', 'floor', 'ceiling',
    'id', 'key', 'doc', 'document', 'matches', 'replace', 'lower-case', 'upper-case',
    'tokenize', 'ends-with', 'current', 'node', 'text', 'comment', 'processing-instruction',
    'child', 'descendant', 'parent', 'ancestor', 'following-sibling', 'preceding-sibling',
    'following', 'preceding', 'attribute', 'self', 'descendant-or-self', 'ancestor-or-self'
}


def parse_dmc_elements(dm_code_node, issue_node=None, lang_node=None) -> Dict[str, Any]:
    if dm_code_node is None:
        return {}
    model = (dm_code_node.get("modelIdentCode") or "").strip()
    sdc = (dm_code_node.get("systemDiffCode") or "").strip()
    sc = (dm_code_node.get("systemCode") or "").strip()
    ssc = (dm_code_node.get("subSystemCode") or "").strip() + (dm_code_node.get("subSubSystemCode") or "").strip()
    assy = (dm_code_node.get("assyCode") or "").strip()
    disassy = (dm_code_node.get("disassyCode") or "").strip() + (dm_code_node.get("disassyCodeVariant") or "").strip()
    info = (dm_code_node.get("infoCode") or "").strip() + (dm_code_node.get("infoCodeVariant") or "").strip()
    ilc = (dm_code_node.get("itemLocationCode") or "").strip()

    parts = [model, sdc, sc, ssc, assy, disassy, info, ilc]
    base_dmc = "DMC-" + "-".join(x for x in parts if x)

    issue_num = ""
    in_work = ""
    if issue_node is not None:
        issue_num = (issue_node.get("issueNumber") or "").strip()
        in_work = (issue_node.get("inWork") or "").strip()

    lang_iso = ""
    country_iso = ""
    if lang_node is not None:
        lang_iso = (lang_node.get("languageIsoCode") or "").strip()
        country_iso = (lang_node.get("countryIsoCode") or "").strip()

    return {
        'base_dmc': base_dmc.lower(),
        'issue_number': issue_num.lower(),
        'in_work': in_work.lower(),
        'language_iso': lang_iso.lower(),
        'country_iso': country_iso.lower()
    }


def extract_dm_metadata(tree: etree._Element, file_info: Dict) -> None:
    """Parses S1000D metadata for reporting."""
    try:
        # Improved metadata extraction: supports any S1000D namespace version
        dm_code_elem = tree.xpath(".//*[local-name()='dmCode']")
        if dm_code_elem:
            dm_code_elem = dm_code_elem[0]
            raw_info = dm_code_elem.get("infoCode", "")
            # We only want the 3-digit Info Code for cleaner filtering
            file_info['info_code'] = raw_info[:3] if raw_info else "N/A"

            full_infoc = raw_info + dm_code_elem.get("infoCodeVariant", "")
            p = [dm_code_elem.get("modelIdentCode", ""), dm_code_elem.get("systemDiffCode", ""),
                 dm_code_elem.get("systemCode", ""),
                 dm_code_elem.get("subSystemCode", "") + dm_code_elem.get("subSubSystemCode", ""),
                 dm_code_elem.get("assyCode", ""),
                 dm_code_elem.get("disassyCode", "") + dm_code_elem.get("disassyCodeVariant", ""),
                 full_infoc, dm_code_elem.get("itemLocationCode", "")]
            file_info['dm_code'] = "-".join(x for x in p if x)

        rpc = tree.xpath(".//*[local-name()='responsiblePartnerCompany']")
        if rpc:
            file_info['rpc'] = rpc[0].get("enterpriseCode", "N/A")
        org = tree.xpath(".//*[local-name()='originator']")
        if org:
            file_info['originator'] = org[0].get("enterpriseCode", "N/A")

        # BREX Reference for 'chain' mode
        brex_ref_node = tree.xpath(".//*[local-name()='brexDmRef']//*[local-name()='dmRef']")
        if brex_ref_node:
            dm_c = brex_ref_node[0].xpath(".//*[local-name()='dmCode']")
            issue_n = brex_ref_node[0].xpath(".//*[local-name()='issueInfo']")
            lang_n = brex_ref_node[0].xpath(".//*[local-name()='language']")

            ref_dmc_dict = parse_dmc_elements(dm_c[0] if dm_c else None,
                                              issue_n[0] if issue_n else None,
                                              lang_n[0] if lang_n else None)
            file_info['brex_ref_detail'] = ref_dmc_dict
            file_info['brex_ref'] = ref_dmc_dict.get('base_dmc', '') + ".xml"
        else:
            brex_ref = tree.xpath(".//*[local-name()='brexDmRef']")
            if brex_ref:
                dm_c = brex_ref[0].xpath(".//*[local-name()='dmCode']")
                if dm_c:
                    dm_c = dm_c[0]
                    p = [dm_c.get("modelIdentCode", ""), dm_c.get("systemDiffCode", ""), dm_c.get("systemCode", ""),
                         dm_c.get("subSystemCode", "") + dm_c.get("subSubSystemCode", ""), dm_c.get("assyCode", ""),
                         dm_c.get("disassyCode", "") + dm_c.get("disassyCodeVariant", ""),
                         dm_c.get("infoCode", "") + dm_c.get("infoCodeVariant", ""), dm_c.get("itemLocationCode", "")]
                    base_dmc = "DMC-" + "-".join(x for x in p if x)
                    file_info['brex_ref'] = base_dmc.lower() + ".xml"
                    file_info['brex_ref_detail'] = {'base_dmc': base_dmc.lower()}

        sloc = tree.get(f"{{{XSI_NS}}}noNamespaceSchemaLocation")
        if not sloc:  # Try SchemaLocation fallback
            sloc_full = tree.get(f"{{{XSI_NS}}}schemaLocation")
            if sloc_full:
                sloc = sloc_full.split()[-1]

        if sloc:
            file_info['schema_location'] = Path(sloc).name
            file_info['schema_location_raw'] = sloc
    except Exception:
        pass


def extract_xsd_rule_id(msg: str) -> str:
    """Extracts a structured diagnostic XSD rule ID from lxml validation messages."""
    msg_lower = msg.lower()
    if "is required but missing" in msg_lower:
        return "XSD_MISSING_ATTRIBUTE"
    if "is not allowed" in msg_lower and "attribute" in msg_lower:
        return "XSD_INVALID_ATTRIBUTE"
    if "not expected" in msg_lower or "is not allowed here" in msg_lower:
        return "XSD_UNEXPECTED_ELEMENT"
    if "missing child" in msg_lower or "expected" in msg_lower:
        return "XSD_MISSING_CHILD"
    if "facet" in msg_lower:
        return "XSD_FACET_VIOLATION"
    if "not a valid value" in msg_lower:
        return "XSD_INVALID_TYPE"
    if "character content other than whitespace" in msg_lower:
        return "XSD_INVALID_TEXT"
    return "XSD_SCHEMA_VIOLATION"


def compile_schema_elements_and_attributes(schema_dir: Path) -> Tuple[set, set]:
    elements = set()
    attributes = set()
    if not schema_dir or not schema_dir.is_dir():
        return elements, attributes
    parser = etree.XMLParser(recover=True, load_dtd=False, no_network=True)
    resolver = SchemaResolver(schema_dir)
    parser.resolvers.add(resolver)
    for xsd_path in schema_dir.glob("**/*.xsd"):
        try:
            tree = etree.parse(str(xsd_path), parser=parser)
            for el in tree.xpath("//*[local-name()='element']"):
                name = el.get("name")
                if name:
                    elements.add(name)
            for attr in tree.xpath("//*[local-name()='attribute']"):
                name = attr.get("name")
                if name:
                    attributes.add(name)
        except Exception:
            pass
    return elements, attributes


def extract_xpath_elements_and_attributes(xpath_str: str) -> Tuple[set, set]:
    clean_str = re.sub(r"'[^']*'|\"[^\"]*\"", "", xpath_str)

    # 1. Extract attributes using @ prefix and attribute:: axis
    attrs_at = re.findall(r'@([a-zA-Z0-9_:-]+)', clean_str)
    attrs_axis = re.findall(r'\battribute::([a-zA-Z0-9_:-]+)', clean_str)
    attributes = set()
    for attr in attrs_at + attrs_axis:
        attributes.add(attr.split(':')[-1])

    # Remove attributes from clean_str to avoid them being parsed as elements
    clean_str = re.sub(r'@([a-zA-Z0-9_:-]+)', '', clean_str)
    clean_str = re.sub(r'\battribute::([a-zA-Z0-9_:-]+)', '', clean_str)

    # 2. Extract elements
    candidates = re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_:-]*)\b', clean_str)
    elements = set()

    axes = {
        'child', 'descendant', 'parent', 'ancestor', 'following-sibling',
        'preceding-sibling', 'following', 'preceding', 'self',
        'descendant-or-self', 'ancestor-or-self', 'namespace', 'attribute'
    }

    for cand in candidates:
        if re.search(rf'\b{re.escape(cand)}\s*\(', clean_str):
            continue
        if cand.lower() in XPATH_KEYWORDS:
            continue
        if cand.lower() in axes:
            continue
        elements.add(cand.split(':')[-1])
    return elements, attributes


def get_node_info(lxml_tree, xpath_query, namespaces) -> Tuple[str, str]:
    """Helper to locate a node in lxml to get its sourceline and exact path."""
    try:
        nodes = lxml_tree.xpath(xpath_query, namespaces=namespaces)
        if nodes and isinstance(nodes[0], etree._Element):
            line = f"Line {nodes[0].sourceline}" if nodes[0].sourceline else "N/A"
            path = lxml_tree.getroottree().getpath(nodes[0])
            return path, line
    except Exception:
        pass
    return xpath_query, "N/A"


def find_lxml_element_for_saxon_node(tree: etree._Element, saxon_node: Any) -> Tuple[Any, str]:
    """
    Finds the corresponding lxml element in the tree for a Saxon node.
    Returns (lxml_element, attribute_name) where attribute_name is set if the node is an attribute.
    """
    if not hasattr(saxon_node, 'node_kind'):
        return None, None

    kind = saxon_node.node_kind
    line_num = getattr(saxon_node, 'line_number', None)

    if not line_num or line_num <= 0:
        return None, None

    tag_name = None
    attr_name = None

    if kind == 1:  # Element
        tag_name = saxon_node.name
    elif kind == 2:  # Attribute
        attr_name = saxon_node.name
        # Try to get parent to find parent's line number and tag name
        try:
            parent = saxon_node.get_parent()
            if parent:
                line_num = getattr(parent, 'line_number', line_num)
                tag_name = parent.name
        except Exception:
            pass
    elif kind == 3:  # Text Node
        try:
            parent = saxon_node.get_parent()
            if parent:
                line_num = getattr(parent, 'line_number', line_num)
                tag_name = parent.name
        except Exception:
            pass

    # Search for matching element in lxml
    candidates = [elem for elem in tree.iter() if elem.sourceline == line_num]
    if not candidates:
        return None, attr_name

    if len(candidates) == 1:
        return candidates[0], attr_name

    if tag_name:
        # Strip prefixes from both tags to compare
        tag_name_clean = tag_name.split(':')[-1].lower()
        for c in candidates:
            c_tag_clean = etree.QName(c.tag).localname.lower()
            if c_tag_clean == tag_name_clean:
                return c, attr_name

    return candidates[0], attr_name


class SchemaResolver(etree.Resolver):
    def __init__(self, schema_dir: Path, schema_mode: str = "auto"):
        self.schema_dir = Path(schema_dir)
        self.schema_mode = schema_mode
        self.local_files = {}
        if self.schema_dir.is_dir():
            for p in self.schema_dir.rglob("*"):
                if p.is_file() and p.suffix.lower() in ('.xsd', '.ent', '.style', '.dtd', '.mod'):
                    self.local_files[p.name.lower()] = p

    def resolve(self, url, pubid, context):
        if not url:
            return None
        filename = Path(url).name
        f_lower = filename.lower()
        if f_lower in self.local_files:
            return self.resolve_filename(str(self.local_files[f_lower]), context)
        if url.startswith(("http://", "https://")) and self.schema_mode in ("auto", "online"):
            try:
                resolved_path = resolve_schema_file(url, self.schema_dir, schema_mode=self.schema_mode)
                if resolved_path and resolved_path.exists():
                    self.local_files[f_lower] = resolved_path
                    return self.resolve_filename(str(resolved_path), context)
            except Exception:
                pass
        return None


def resolve_schema_file(schema_location: str, schema_dir: Path, xml_file_path: Path = None,
                        schema_mode: str = "auto") -> Path:
    """
    Resolves a schema location (URL or local path) to a local XSD file path.
    If the schema is a URL and not found locally, it downloads and caches it depending on schema_mode.
    """
    if not schema_location:
        return None

    schema_dir = Path(schema_dir)
    filename = Path(schema_location).name

    # 1. Check if the schema_location is a URL
    if schema_location.startswith(("http://", "https://")):
        url_match = re.match(r'https?://[^/]+/(.*)', schema_location)
        url_suffix = url_match.group(1) if url_match else filename

        cache_path = schema_dir / "cache" / url_suffix

        # Check cache first
        if cache_path.exists():
            return cache_path

        # Check direct local path corresponding to URL structure under schema_dir
        direct_local = schema_dir / url_suffix
        if direct_local.exists():
            return direct_local

        # If schema_mode is 'online' or 'auto', search for filename recursively in schema_dir first (excluding cache)
        if schema_mode in ('auto', 'local'):
            local_candidates = []
            if schema_dir.is_dir():
                for p in schema_dir.rglob("*.xsd"):
                    if "cache" in p.parts:
                        continue
                    if p.name.lower() == filename.lower():
                        local_candidates.append(p)

            if local_candidates:
                # If multiple local candidates exist, try to find the one matching the URL version/path
                # e.g., if url_suffix contains "S1000D_4-1" and a candidate path has "4-1" or "4.1" or "4_1"
                version_match = re.search(r'S1000D_([0-9]+)[-_.]([0-9]+)', url_suffix, re.I)
                if version_match:
                    v_str_1 = f"{version_match.group(1)}.{version_match.group(2)}"
                    v_str_2 = f"{version_match.group(1)}-{version_match.group(2)}"
                    for cand in local_candidates:
                        cand_str = str(cand)
                        if v_str_1 in cand_str or v_str_2 in cand_str:
                            return cand
                return local_candidates[0]

        # If schema_mode is 'local', do not download
        if schema_mode == 'local':
            return None

        # Download online schema and cache it
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import urllib.request
            req = urllib.request.Request(
                schema_location,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                cache_path.write_bytes(response.read())
            print(f"[i] Cached online schema: {schema_location} -> {cache_path}")
            return cache_path
        except Exception as e:
            print(f"[!] Failed to download online schema {schema_location}: {e}")
            return None

    # 2. Local relative path or filename
    else:
        # Try resolving relative to xml_file_path if provided
        if xml_file_path:
            rel_path = Path(xml_file_path).parent / schema_location
            if rel_path.exists():
                return rel_path

        # Try resolving relative to schema_dir
        direct_local = schema_dir / schema_location
        if direct_local.exists():
            return direct_local

        # Recursive search in schema_dir
        if schema_dir.is_dir():
            for p in schema_dir.rglob("*.xsd"):
                if p.name.lower() == filename.lower():
                    return p

    return None


def is_suppressed_violation(error_type: str, rule_id: str, dm_code: str, xpath: str,
                            message: str, baseline_rules: list) -> bool:
    """Centralized baseline suppression logic supporting error_type, rule_id, dm_code, xpath, and message."""
    if not baseline_rules:
        return False

    m_type = error_type or ""
    m_rule = rule_id or ""
    m_dm = dm_code or ""
    m_xpath = xpath or ""
    m_msg = message or ""

    for rule in baseline_rules:
        if rule.get('error_type') and not re.search(rule['error_type'], m_type, re.I):
            continue
        if rule.get('rule_id') and not re.search(rule['rule_id'], m_rule, re.I):
            continue
        if rule.get('dm_code') and not re.search(rule['dm_code'], m_dm, re.I):
            continue
        if rule.get('xpath') and not re.search(rule['xpath'], m_xpath, re.I):
            continue
        if rule.get('message') and not re.search(rule['message'], m_msg, re.I):
            continue
        return True
    return False


def load_csdb_manifest(manifest_path: Path) -> Tuple[set, set]:
    """
    Loads known external CSDB Data Module Codes (DMC/PMC) and Resource identifiers (ICN)
    from a JSON, CSV, or plain-text manifest file to prevent false positives on partial deliveries.
    """
    known_dmcs = set()
    known_resources = set()
    if not manifest_path or not Path(manifest_path).exists():
        return known_dmcs, known_resources

    p = Path(manifest_path)
    try:
        content = p.read_text(encoding='utf-8-sig')
        if p.suffix.lower() == '.json':
            import json
            data = json.loads(content)
            if isinstance(data, dict):
                for d in data.get('dmcs', []) + data.get('modules', []):
                    norm = re.sub(r'^(?:DMC|PMC|DMLC)-', '', str(d).strip(), flags=re.I).split('_')[0]
                    known_dmcs.add(norm.upper().replace('_', '-'))
                for r in data.get('resources', []) + data.get('icns', []):
                    known_resources.add(Path(str(r).strip()).stem.upper())
            elif isinstance(data, list):
                for item in data:
                    s = str(item).strip()
                    if s.upper().startswith('ICN-'):
                        known_resources.add(Path(s).stem.upper())
                    else:
                        norm = re.sub(r'^(?:DMC|PMC|DMLC)-', '', s, flags=re.I).split('_')[0]
                        known_dmcs.add(norm.upper().replace('_', '-'))
        else:
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                for token in re.split(r'[;,\t]', line):
                    token = token.strip().strip('"\'')
                    if not token:
                        continue
                    stem = Path(token).stem.upper()
                    if stem.startswith('ICN-'):
                        known_resources.add(stem)
                    else:
                        norm = re.sub(r'^(?:DMC|PMC|DMLC)-', '', stem, flags=re.I).split('_')[0]
                        if '-' in norm:
                            known_dmcs.add(norm.upper().replace('_', '-'))
    except Exception:
        pass

    return known_dmcs, known_resources


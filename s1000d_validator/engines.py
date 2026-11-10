"""
S1000D Validator - Modular Engines (v8.6.1)
-------------------------------------------
This module defines the internal engine API and provides specialized
validation engines (Schema, BREX, Schematron, Integrity) for better maintenance.
"""

import re
import difflib
from lxml import etree
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from s1000d_validator.utils import find_lxml_element_for_saxon_node, is_suppressed_violation


@dataclass
class Violation:
    """Standardized representation of an XML rule violation."""
    level: int
    message: str
    error_type: str
    rule_id: str = "GENERIC"
    xpath: str = "N/A"
    location: str = "N/A"
    attribute: str = "N/A"

    def to_dict(self, file_info: Dict[str, Any]) -> Dict[str, Any]:
        """Merges violation data with file metadata for reporting/database."""
        d = asdict(self)
        d.update({
            'filename': file_info.get('filename', 'N/A'),
            'dm_code': file_info.get('dm_code', 'N/A'),
            'info_code': file_info.get('info_code', 'N/A'),
            'rpc': file_info.get('rpc', 'N/A'),
            'originator': file_info.get('originator', 'N/A'),
            'schema_location': file_info.get('schema_location', 'N/A')
        })
        return d


class BaseEngine:
    """Base API for validation modules."""
    def __init__(self, config: Dict[str, Any]):
        self.config = config

    def run(self, tree: Any, tree_doc: Any, file_info: Dict[str, Any], **kwargs) -> List[Violation]:
        """Executes the validation logic. Must be overridden by subclasses."""
        raise NotImplementedError("Each engine must implement the 'run' method.")

    def is_suppressed(self, violation: Violation, baseline_rules: List[Dict], file_info: Dict[str, Any]) -> bool:
        """Centralized suppression logic (Baseline Support)."""
        return is_suppressed_violation(
            violation.error_type,
            violation.rule_id,
            file_info.get('dm_code', ''),
            violation.xpath,
            violation.message,
            baseline_rules
        )


class IntegrityEngine(BaseEngine):
    """Handles Broken Link and Missing Resource validation (v8.7.0)."""

    def run(self, tree: Any, tree_doc: Any, file_info: Dict[str, Any], **kwargs) -> List[Violation]:
        violations = []

        # Pull global scan results from parameters
        avail_dmcs = kwargs.get('available_dmcs', set())
        avail_res = kwargs.get('available_resources', set())
        baseline_rules = kwargs.get('baseline_rules', [])

        sev_map = {"ERROR": 40, "WARNING": 30, "INFO": 20}
        sev_name = self.config.get("integrity_severity", "WARNING").upper()
        sev_level = sev_map.get(sev_name, 30)

        # 1. Image / Resource Check (ICN)
        if not self.config.get('no_resource_checks', False):
            xp_expr = "//*[local-name()='graphic'] | //*[local-name()='symbol'] | //*[local-name()='controlIndicator'] | //*[local-name()='multimediaObject']"
            for g in tree.xpath(xp_expr):
                icn = g.get('infoEntityIdent')
                if icn:
                    norm_icn = icn.upper().strip()
                    if norm_icn not in avail_res:
                        line = f"Line {g.sourceline}" if g.sourceline else "N/A"
                        xpath = tree_doc.getpath(g)
                        temp_v = Violation(
                            level=sev_level, message="Missing Resource Reference", error_type="Resource",
                            rule_id="RES_MISSING", xpath=xpath, location=line, attribute=f"ICN: {icn}"
                        )
                        if not self.is_suppressed(temp_v, baseline_rules, file_info):
                            violations.append(temp_v)

        # 2. DM & Internal Reference Check (DMC / internalRef)
        if not self.config.get('no_reference_checks', False):
            avail_dmcs_list = list(avail_dmcs) if avail_dmcs else []
            for dr in tree.xpath("//*[local-name()='dmRef']"):
                dmc_elem = dr.xpath(".//*[local-name()='dmCode']")
                if dmc_elem:
                    dmc_elem = dmc_elem[0]
                    p = [dmc_elem.get("modelIdentCode", ""), dmc_elem.get("systemDiffCode", ""),
                         dmc_elem.get("systemCode", ""),
                         dmc_elem.get("subSystemCode", "") + dmc_elem.get("subSubSystemCode", ""),
                         dmc_elem.get("assyCode", ""),
                         dmc_elem.get("disassyCode", "") + dmc_elem.get("disassyCodeVariant", ""),
                         dmc_elem.get("infoCode", "") + dmc_elem.get("infoCodeVariant", ""),
                         dmc_elem.get("itemLocationCode", "")]
                    dmc_str = "-".join(x for x in p if x).upper()

                    if dmc_str not in avail_dmcs:
                        line = f"Line {dr.sourceline}" if dr.sourceline else "N/A"
                        xpath = tree_doc.getpath(dr)
                        attr_str = f"DMC: {dmc_str}"
                        if avail_dmcs_list:
                            close = difflib.get_close_matches(dmc_str, avail_dmcs_list, n=1, cutoff=0.8)
                            if close:
                                attr_str += f" (Did you mean: {close[0]}?)"
                        temp_v = Violation(
                            level=sev_level, message="Broken DM Reference", error_type="Reference",
                            rule_id="LINK_BROKEN", xpath=xpath, location=line, attribute=attr_str
                        )
                        if not self.is_suppressed(temp_v, baseline_rules, file_info):
                            violations.append(temp_v)

            # Check pmRef (Publication Module Reference) targets
            for pmr in tree.xpath("//*[local-name()='pmRef']"):
                pmc_elem = pmr.xpath(".//*[local-name()='pmCode']")
                if pmc_elem:
                    pmc_elem = pmc_elem[0]
                    p = [
                        pmc_elem.get("modelIdentCode", ""),
                        pmc_elem.get("pmIssuer", ""),
                        pmc_elem.get("pmNumber", ""),
                        pmc_elem.get("pmVolume", "")
                    ]
                    pmc_core = "-".join(x for x in p if x).upper()
                    pmc_prefixed = f"PMC-{pmc_core}"
                    if pmc_core and pmc_core not in avail_dmcs and pmc_prefixed not in avail_dmcs:
                        line = f"Line {pmr.sourceline}" if pmr.sourceline else "N/A"
                        xpath = tree_doc.getpath(pmr)
                        temp_v = Violation(
                            level=sev_level, message="Broken PM Reference", error_type="Reference",
                            rule_id="PM_LINK_BROKEN", xpath=xpath, location=line,
                            attribute=f"PMC: {pmc_prefixed}"
                        )
                        if not self.is_suppressed(temp_v, baseline_rules, file_info):
                            violations.append(temp_v)

            # Check internalRef targets within the same XML document
            internal_refs = tree.xpath("//*[local-name()='internalRef']")
            if internal_refs:
                doc_ids = set(tree.xpath("//@id"))
                for iref in internal_refs:
                    target_id = iref.get("internalRefId")
                    if target_id and target_id not in doc_ids:
                        line = f"Line {iref.sourceline}" if iref.sourceline else "N/A"
                        xpath = tree_doc.getpath(iref)
                        temp_v = Violation(
                            level=sev_level, message="Broken Internal Reference", error_type="Reference",
                            rule_id="INTERNAL_LINK_BROKEN", xpath=xpath, location=line,
                            attribute=f"internalRefId: {target_id}"
                        )
                        if not self.is_suppressed(temp_v, baseline_rules, file_info):
                            violations.append(temp_v)

        return violations


class SaxonBrexEngine(BaseEngine):
    """Handles deep-logic BREX validation (Saxon-based, v8.7.0)."""

    def run(self, tree: Any, tree_doc: Any, file_info: Dict[str, Any], **kwargs) -> List[Violation]:
        violations = []
        rules = kwargs.get('rules', [])
        notation_rules = kwargs.get('notation_rules', [])
        saxon_xp = kwargs.get('saxon_xp')
        ns = kwargs.get('ns', {})
        baseline_rules = kwargs.get('baseline_rules', [])

        sev_map = {"ERROR": 40, "WARNING": 30, "INFO": 20}
        sev_name = self.config.get("brex_severity", "ERROR").upper()
        brex_sev_level = sev_map.get(sev_name, 40)

        # Evaluate BREX notationRuleList if present (REQ-303)
        if notation_rules and hasattr(tree_doc, 'docinfo') and tree_doc.docinfo.internalDTD:
            try:
                dtd_notations = {n.name.upper(): n.name for n in tree_doc.docinfo.internalDTD.notations()}
                for n_Entity in tree_doc.docinfo.internalDTD.entities():
                    if getattr(n_Entity, 'content', None) and hasattr(n_Entity, 'name'):
                        pass
                allowed_set = {nr['notation_name'].upper() for nr in notation_rules if nr['flag'] == '1'}
                for nr in notation_rules:
                    n_target = nr['notation_name'].upper()
                    if nr['flag'] == '0' and n_target in dtd_notations:
                        v = Violation(
                            level=brex_sev_level, message=f"BREX: {nr['message']}",
                            error_type="BREX", rule_id=nr['id'], xpath="/DOCTYPE/NOTATION",
                            location="Line 1", attribute=f"NOTATION: {dtd_notations[n_target]} (FORBIDDEN)"
                        )
                        if not self.is_suppressed(v, baseline_rules, file_info):
                            violations.append(v)
                if allowed_set:
                    default_allow_rule = next((nr for nr in notation_rules if nr['flag'] == '1'), notation_rules[0])
                    for dtd_n_upper, dtd_n_orig in dtd_notations.items():
                        if dtd_n_upper not in allowed_set:
                            v = Violation(
                                level=brex_sev_level, message=f"BREX: {default_allow_rule['message']}",
                                error_type="BREX", rule_id=default_allow_rule['id'], xpath="/DOCTYPE/NOTATION",
                                location="Line 1", attribute=f"NOTATION: {dtd_n_orig} (NOT ALLOWED)"
                            )
                            if not self.is_suppressed(v, baseline_rules, file_info):
                                violations.append(v)
            except Exception:
                pass

        for r in rules:
            try:
                # 1. Performance Path: Saxon -> LXML Fallback
                res = None
                if saxon_xp:
                    try:
                        res = saxon_xp.evaluate(r['query'])
                    except Exception as e:
                        if self.config.get('debug'):
                            print(f"      [DEBUG] Saxon XPath Error on '{r['query']}': {e}")

                if res is None:  # Fallback (lxml)
                    if r.get('lxml_selector'):
                        try:
                            res = r['lxml_selector'](tree)
                        except Exception:
                            pass

                # 2. Logic Evaluation (Flag 0, 1, 2)
                if not res:
                    if r['flag'] == "1":
                        # Mandatory object missing
                        # Extract the base tag name from XPath for context
                        tag_name = re.findall(r'([a-zA-Z0-9_:-]+)(?=\[|$)', r['query'].split('/')[-1])
                        target = tag_name[0] if tag_name else "Element"

                        v = Violation(
                            level=brex_sev_level, message=f"BREX: {r['message']}",
                            error_type="BREX", rule_id=r['id'], xpath=r['query'],
                            location="N/A", attribute=f"MISSING: {target}"
                        )
                        if not self.is_suppressed(v, baseline_rules, file_info):
                            violations.append(v)
                    continue

                if r['flag'] == "0":
                    # Forbidden object found
                    for el in res:
                        # Ensure we are only reporting on actual Nodes (v8.4.2)
                        is_node = isinstance(el, etree._Element)
                        if not is_node and hasattr(el, 'node_kind'):  # Saxon XDM Node
                            is_node = el.node_kind in [1, 2, 3, 4]  # document, element, attribute, text

                        if not is_node:
                            continue  # Skip booleans or non-node results

                        v = self.create_violation(el, r, tree_doc)
                        if not self.is_suppressed(v, baseline_rules, file_info):
                            violations.append(v)

                elif r['flag'] in ["1", "2"]:
                    # Check allowed values if any are specified
                    v_allowed = r.get('v_allowed', [])
                    v_not_allowed = r.get('v_not_allowed', [])
                    v_patterns = r.get('v_patterns', [])
                    v_ranges = r.get('v_ranges', [])

                    has_restrictions = bool(v_allowed or v_not_allowed or v_patterns or v_ranges)

                    for el in res:
                        # Ensure we are only reporting on actual Nodes
                        is_node = isinstance(el, etree._Element)
                        if not is_node and hasattr(el, 'node_kind'):  # Saxon
                            is_node = el.node_kind in [1, 2, 3, 4]

                        if not is_node:
                            continue

                        try:
                            if not has_restrictions:
                                continue  # Any value allowed if no objectValue elements exist

                            # Value extraction
                            if hasattr(el, 'string_value'):
                                val = el.string_value
                            elif hasattr(el, 'text'):
                                val = el.text
                            else:
                                val = str(el)

                            val = (val or "").strip()
                            # Refactored Constraint Evaluation:
                            # S1000D rules check that a value satisfies at least one allowed constraint (if defined),
                            # AND does not violate any disallowed/negative constraint.
                            has_allowed = bool(v_allowed) or any(p['allowed'] for p in v_patterns) or any(
                                rg['allowed'] for rg in v_ranges)

                            is_allowed = True
                            if has_allowed:
                                matched_allowed = False
                                if val in v_allowed:
                                    matched_allowed = True
                                if not matched_allowed:
                                    for p in v_patterns:
                                        if p['allowed'] and p['pattern'].match(val):
                                            matched_allowed = True
                                            break
                                if not matched_allowed:
                                    for rng in v_ranges:
                                        if rng['allowed']:
                                            try:
                                                low, high = rng['range'][0], rng['range'][1]
                                                try:
                                                    f_val = float(val.replace(',', '.'))
                                                    low_f = float(low.replace(',', '.'))
                                                    high_f = float(high.replace(',', '.'))
                                                    in_range = low_f <= f_val <= high_f
                                                except (ValueError, TypeError):
                                                    in_range = low <= val <= high
                                                if in_range:
                                                    matched_allowed = True
                                                    break
                                            except Exception:
                                                pass
                                is_allowed = matched_allowed

                            # If it passes allowed constraints (or none exist), check negative constraints
                            if is_allowed:
                                if val in v_not_allowed:
                                    is_allowed = False

                                if is_allowed:
                                    for p in v_patterns:
                                        if not p['allowed'] and p['pattern'].match(val):
                                            is_allowed = False
                                            break

                                if is_allowed:
                                    for rng in v_ranges:
                                        if not rng['allowed']:
                                            try:
                                                low, high = rng['range'][0], rng['range'][1]
                                                try:
                                                    f_val = float(val.replace(',', '.'))
                                                    low_f = float(low.replace(',', '.'))
                                                    high_f = float(high.replace(',', '.'))
                                                    in_range = low_f <= f_val <= high_f
                                                except (ValueError, TypeError):
                                                    in_range = low <= val <= high
                                                if in_range:
                                                    is_allowed = False
                                                    break
                                            except Exception:
                                                pass

                            if not is_allowed:
                                v = self.create_violation(el, r, tree_doc)

                                # Extract attribute name if we are checking an attribute
                                attr_match = re.search(r"@([a-zA-Z0-9_:-]+)$", r['query'])
                                if attr_match:
                                    v.attribute = f"@{attr_match.group(1)} ('{val}')"
                                else:
                                    # Fallback to tag name if possible
                                    tag_match = re.findall(r'([a-zA-Z0-9_:-]+)', r['query'].split('/')[-1])
                                    tag = f"<{tag_match[0]}> " if tag_match else ""
                                    v.attribute = f"{tag}('{val}')"

                                # Build detailed validation message suffix
                                detail = f"Value '{val}' is invalid."
                                if v_allowed:
                                    detail = f"Value '{val}' is not allowed. Allowed values: {', '.join(f'\"{x}\"' for x in v_allowed)}"
                                elif v_not_allowed:
                                    detail = f"Value '{val}' is forbidden. Forbidden values: {', '.join(f'\"{x}\"' for x in v_not_allowed)}"
                                elif v_patterns:
                                    pat_details = []
                                    for p in v_patterns:
                                        p_str = p['pattern'].pattern
                                        pat_details.append(f"{'matches' if p['allowed'] else 'must not match'} /{p_str}/")
                                    detail = f"Value '{val}' does not conform: {', '.join(pat_details)}"
                                elif v_ranges:
                                    rng_details = []
                                    for rng in v_ranges:
                                        r_str = f"{rng['range'][0]}~{rng['range'][1]}"
                                        rng_details.append(
                                            f"{'must be in range' if rng['allowed'] else 'must not be in range'} [{r_str}]"
                                        )
                                    detail = f"Value '{val}' does not conform: {', '.join(rng_details)}"

                                v.message = f"{v.message} ({detail})"

                                if not self.is_suppressed(v, baseline_rules, file_info):
                                    violations.append(v)
                        except Exception as e:
                            if self.config.get('debug'):
                                print(f"      [DEBUG] Error evaluating element in rule {r['id']}: {e}")
                            continue
            except Exception as e:
                if self.config.get('debug'):
                    print(f"      [DEBUG] Error in rule {r['id']} processing: {e}")
                continue

        if self.config.get('debug') and violations:
            print(f"   [DEBUG] Found {len(violations)} BREX violations in {file_info['filename']}")
        return violations

    def create_violation(self, node: Any, rule: Dict[str, Any], tree_doc: Any) -> Violation:
        """Helper to create a structured Violation from an XML result element."""
        el_xpath, el_line = rule['query'], "N/A"
        msg = f"BREX: {rule['message']}"

        # Determine exact XPath and Line
        el_attr = "N/A"
        if isinstance(node, etree._Element):
            el_xpath = tree_doc.getpath(node)
            if node.sourceline:
                el_line = f"Line {node.sourceline}"

            # Sub-Attribute Deep Inspection (Flag 0)
            if rule.get('sub_attrs'):
                for attr in rule['sub_attrs']:
                    if attr in node.attrib:
                        el_xpath += f"/@{attr}"
                        el_attr = f"@{attr} (FORBIDDEN)"
                        break
        elif hasattr(node, 'line_number'):  # Saxon / Generic
            try:
                if node.line_number:
                    el_line = f"Line {node.line_number}"

                # Map Saxon node to lxml element for exact path and attribute tracking
                lxml_el, attr_name = find_lxml_element_for_saxon_node(tree_doc.getroot(), node)
                if lxml_el is not None:
                    el_xpath = tree_doc.getpath(lxml_el)
                    if attr_name:
                        el_xpath += f"/@{attr_name}"
                        el_attr = f"@{attr_name}"
                    elif rule.get('sub_attrs'):
                        for attr in rule['sub_attrs']:
                            if attr in lxml_el.attrib:
                                el_xpath += f"/@{attr}"
                                el_attr = f"@{attr} (FORBIDDEN)"
                                break
                else:
                    # Fallback if mapping failed
                    if hasattr(node, 'node_kind') and node.node_kind == 2:
                        el_xpath = f"{rule['query']}/@{node.name}"
                        el_attr = f"@{node.name}"
            except Exception:
                pass

        # Determine severity from config
        sev_map = {"ERROR": 40, "WARNING": 30, "INFO": 20}
        sev_name = self.config.get("brex_severity", "ERROR").upper()
        sev_level = sev_map.get(sev_name, 40)

        return Violation(
            level=sev_level, message=msg, error_type="BREX", rule_id=rule['id'],
            xpath=el_xpath, location=el_line, attribute=el_attr
        )


class SaxonSchematronEngine(BaseEngine):
    """Handles ISO-Schematron validation (Saxon-based, v8.3.4)."""

    SVRL_NS = "http://purl.oclc.org/dsdl/svrl"

    def run(self, tree: Any, tree_doc: Any, file_info: Dict[str, Any], **kwargs) -> List[Violation]:
        violations = []
        validators = kwargs.get('validators', [])
        saxon_doc = kwargs.get('saxon_doc')
        ns = kwargs.get('ns', {})
        baseline_rules = kwargs.get('baseline_rules', [])

        if not validators or not saxon_doc:
            return violations

        for sch in validators:
            try:
                # 1. Transform Schematron to SVRL
                svrl_str = sch['validator'].transform_to_string(xdm_node=saxon_doc)

                # 2. Extract violations from SVRL
                if "failed-assert" in svrl_str or "successful-report" in svrl_str:
                    svrl_tree = etree.fromstring(svrl_str.encode())
                    fail_path = "//svrl:failed-assert | //svrl:successful-report"
                    for fail in svrl_tree.xpath(fail_path, namespaces={'svrl': self.SVRL_NS}):
                        default_msg = "Report triggered" if "successful-report" in fail.tag else "Assertion failed"
                        m = fail.findtext(f"{{{self.SVRL_NS}}}text") or default_msg
                        m = m.strip()
                        sch_loc = fail.get('location', '')
                        el_line = "N/A"

                        # 3. Synchronize with lxml tree for precise line numbers
                        if sch_loc:
                            try:
                                match_el = tree.xpath(sch_loc, namespaces=ns)
                                if match_el and isinstance(match_el[0], etree._Element) and match_el[0].sourceline:
                                    el_line = f"Line {match_el[0].sourceline}"
                            except Exception:
                                pass

                        # Determine severity from config
                        sev_map = {"ERROR": 40, "WARNING": 30, "INFO": 20}
                        sev_name = self.config.get("sch_severity", "ERROR").upper()
                        sev_level = sev_map.get(sev_name, 40)

                        # Determine context (tag name) from svrl:location
                        ctx_tag = "N/A"
                        if sch_loc:
                            t_match = re.findall(r'([a-zA-Z0-9_:-]+)(?=\[|$)', sch_loc.split('/')[-1])
                            if t_match:
                                ctx_tag = f"<{t_match[0]}>"

                        # Resolve rule_id with priority: assert/@id -> fired-rule/@id -> active-pattern/@id -> filename
                        rule_id = fail.get('id')
                        if not rule_id:
                            fired_id_list = fail.xpath("preceding-sibling::svrl:fired-rule[1]/@id",
                                                       namespaces={'svrl': self.SVRL_NS})
                            if fired_id_list:
                                rule_id = fired_id_list[0]
                        if not rule_id:
                            pat_id_list = fail.xpath("preceding-sibling::svrl:active-pattern[1]/@id",
                                                     namespaces={'svrl': self.SVRL_NS})
                            rule_id = pat_id_list[0] if pat_id_list else sch['name']

                        v = Violation(
                            level=sev_level, message=f"SCH: {m}",
                            error_type="Schematron", rule_id=rule_id,
                            xpath=sch_loc, location=el_line, attribute=ctx_tag
                        )

                        if not self.is_suppressed(v, baseline_rules, file_info):
                            violations.append(v)

            except Exception:
                continue

        return violations

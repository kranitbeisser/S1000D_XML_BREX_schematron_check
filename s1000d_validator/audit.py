import re
import difflib
import elementpath
from typing import List, Dict, Any
from pathlib import Path
from lxml import etree
from s1000d_validator.utils import (
    STANDARD_NAMESPACES,
    XSI_NS,
    compile_schema_elements_and_attributes,
    extract_xpath_elements_and_attributes,
    resolve_schema_file
)


def get_suggestion(name: str, possibilities: set) -> str:
    if not possibilities:
        return ""
    name_lower = name.lower()
    poss_list = list(possibilities)
    for poss in poss_list:
        if poss.lower() == name_lower:
            return f" Did you mean '{poss}'?"
    matches = difflib.get_close_matches(name, poss_list, n=1, cutoff=0.7)
    if matches:
        return f" Did you mean '{matches[0]}'?"
    return ""


def validate_brex_file(b_path: str, schema_dir: Any = None, schema_mode: str = "auto",
                      allowed_versions: List[str] = None, precompiled_elements: set = None,
                      precompiled_attributes: set = None) -> List[Dict]:
    """Audits a BREX file for structural and logical errors (v8.4.1)."""
    violations = []
    fname = Path(b_path).name
    try:
        tree = etree.parse(b_path)

        # Check BREX own schema version if allowed_versions is configured
        if allowed_versions:
            sloc = tree.getroot().get(f"{{{XSI_NS}}}noNamespaceSchemaLocation")
            if not sloc:
                sloc_full = tree.getroot().get(f"{{{XSI_NS}}}schemaLocation")
                if sloc_full:
                    sloc = sloc_full.split()[-1]
            detected_version = None
            if sloc:
                version_match = re.search(r'S1000D_([0-9]+)[-_.]([0-9]+)', sloc, re.I)
                if version_match:
                    detected_version = f"{version_match.group(1)}.{version_match.group(2)}"

            if detected_version and detected_version not in allowed_versions:
                violations.append({
                    'message': f"Version Violation: BREX file references S1000D version '{detected_version}', "
                               f"which is not allowed. Allowed versions: {', '.join(allowed_versions)}.",
                    'level': 40, 'type': 'Config', 'xpath': '/*'
                })

            # Check contextRules rulesContext versions
            for ctx in tree.xpath("//@rulesContext"):
                ctx_str = str(ctx)
                ctx_version = None
                version_match = re.search(r'S1000D_([0-9]+)[-_.]([0-9]+)', ctx_str, re.I)
                if version_match:
                    ctx_version = f"{version_match.group(1)}.{version_match.group(2)}"
                if ctx_version and ctx_version not in allowed_versions:
                    violations.append({
                        'message': f"Version Violation: rulesContext refers to S1000D version '{ctx_version}' "
                                   f"which is not allowed. Allowed versions: {', '.join(allowed_versions)}.",
                        'level': 40, 'type': 'Config', 'xpath': '//@rulesContext'
                    })

        # Pre-resolve / download referenced schemas
        if schema_dir:
            try:
                # Find rulesContext attributes and download/cache if URLs
                for ctx in tree.xpath("//@rulesContext"):
                    resolve_schema_file(str(ctx), Path(schema_dir), schema_mode=schema_mode)
                # Find noNamespaceSchemaLocation and download/cache
                sloc = tree.getroot().get(f"{{{XSI_NS}}}noNamespaceSchemaLocation")
                if sloc:
                    resolve_schema_file(sloc, Path(schema_dir), schema_mode=schema_mode)
            except Exception:
                pass

        # Parse XML namespaces declared in the BREX file itself
        declared_namespaces = set(tree.getroot().nsmap.keys())
        if None in declared_namespaces:
            declared_namespaces.remove(None)

        # Compile schemas
        schema_elements, schema_attributes = set(), set()
        if precompiled_elements is not None and precompiled_attributes is not None:
            schema_elements, schema_attributes = precompiled_elements, precompiled_attributes
        elif schema_dir:
            schema_elements, schema_attributes = compile_schema_elements_and_attributes(Path(schema_dir))

        # 1. Check for basic BREX structure
        rules = tree.xpath("//*[local-name()='structureObjectRule']")
        if not rules:
            violations.append({
                'message': "BREX file contains no rules (structureObjectRule missing).",
                'level': 30, 'type': 'Config'
            })

        for rule in rules:
            rid = rule.get('id', 'N/A')
            p_els = rule.xpath(".//*[local-name()='objectPath']")
            u_el = rule.xpath(".//*[local-name()='objectUse']")

            if not p_els or not p_els[0].text:
                violations.append({
                    'message': f"Rule {rid}: Missing objectPath or empty text.",
                    'level': 40, 'type': 'Config', 'xpath': tree.getpath(rule)
                })
            else:
                p_el = p_els[0]
                p_text = p_el.text.strip()

                # Check for dirty attributes (v8.4.3)
                flag_raw = p_el.get("allowedObjectFlag")
                if flag_raw:
                    if flag_raw != flag_raw.strip():
                        violations.append({
                            'message': f"Rule {rid}: Dirty attribute 'allowedObjectFlag' "
                                       f"(contains spaces: '{flag_raw}').",
                            'level': 30, 'type': 'Config', 'xpath': tree.getpath(p_el)
                        })
                    if flag_raw.strip() not in ["0", "1", "2"]:
                        violations.append({
                            'message': f"Rule {rid}: Illegal allowedObjectFlag value '{flag_raw.strip()}'.",
                            'level': 40, 'type': 'Config', 'xpath': tree.getpath(p_el)
                        })

                # 2. Test XPath validity via elementpath
                try:
                    elementpath.Selector(p_text, namespaces=STANDARD_NAMESPACES)
                except Exception as e:
                    violations.append({
                        'message': f"Rule {rid}: Invalid XPath syntax '{p_text}' -> {e}",
                        'level': 40, 'type': 'Config', 'xpath': tree.getpath(p_el)
                    })

                # 2b. Validate elements and attributes against schemas
                xpath_els, xpath_attrs = extract_xpath_elements_and_attributes(p_text)
                if schema_elements:
                    ignored_els = {'Description', 'about', 'href', 'type', 'title'}
                    ignored_attrs = {'about', 'href', 'type', 'lang', 'title'}

                    for el in xpath_els:
                        if el not in schema_elements and el not in ignored_els:
                            sugg = get_suggestion(el, schema_elements)
                            violations.append({
                                'message': f"Rule {rid}: XPath references element '{el}' not defined "
                                           f"in S1000D XSD schemas. Rule may be dead.{sugg}",
                                'level': 30, 'type': 'Config', 'xpath': tree.getpath(p_el)
                            })

                    for attr in xpath_attrs:
                        if attr not in schema_attributes and attr not in ignored_attrs:
                            sugg = get_suggestion(attr, schema_attributes)
                            violations.append({
                                'message': f"Rule {rid}: XPath references attribute '{attr}' not defined "
                                           f"in S1000D XSD schemas. Rule may be dead.{sugg}",
                                'level': 30, 'type': 'Config', 'xpath': tree.getpath(p_el)
                            })

                # 2c. Check for undeclared namespaces in XPath
                clean_str = re.sub(r"'[^']*'", "", p_text)
                clean_str = re.sub(r'"[^"]*"', "", clean_str)
                prefixes = set(re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*):(?!:)', clean_str))
                for prefix in prefixes:
                    if prefix not in STANDARD_NAMESPACES and prefix not in declared_namespaces:
                        violations.append({
                            'message': f"Rule {rid}: Undeclared namespace prefix '{prefix}' in XPath '{p_text}'.",
                            'level': 40, 'type': 'Config', 'xpath': tree.getpath(p_el)
                        })

            if not u_el or not u_el[0].text:
                violations.append({
                    'message': f"Rule {rid}: Missing objectUse description.",
                    'level': 30, 'type': 'Config', 'xpath': tree.getpath(rule)
                })

            # 3. Audit objectValues
            for v_el in rule.xpath(".//*[local-name()='objectValue']"):
                v_form = v_el.get("valueForm")
                if v_form:
                    if v_form != v_form.strip():
                        violations.append({
                            'message': f"Rule {rid}: Dirty attribute 'valueForm' (contains spaces: '{v_form}').",
                            'level': 30, 'type': 'Config', 'xpath': tree.getpath(v_el)
                        })
                    if v_form.strip() not in ["single", "range", "pattern"]:
                        violations.append({
                            'message': f"Rule {rid}: Illegal valueForm '{v_form.strip()}'.",
                            'level': 40, 'type': 'Config', 'xpath': tree.getpath(v_el)
                        })

    except etree.XMLSyntaxError as e:
        violations.append({'message': f"XML Syntax Error: {e}", 'level': 50, 'type': 'Config'})
    except Exception as e:
        violations.append({'message': f"Fatal Rule Loader Error: {e}", 'level': 50, 'type': 'Config'})

    return violations


def validate_schematron_file(s_path: str, schema_dir: Any = None, schema_mode: str = "auto",
                             allowed_versions: List[str] = None, precompiled_elements: set = None) -> List[Dict]:
    """Audits a Schematron file for syntax and schema compatibility."""
    violations = []
    fname = Path(s_path).name
    try:
        tree = etree.parse(s_path)

        # Parse XML namespaces declared in the Schematron file
        declared_namespaces = set(tree.getroot().nsmap.keys())
        if None in declared_namespaces:
            declared_namespaces.remove(None)

        # Compile schemas
        schema_elements = set()
        if precompiled_elements is not None:
            schema_elements = precompiled_elements
        elif schema_dir:
            schema_elements, _ = compile_schema_elements_and_attributes(Path(schema_dir))

        # Check patterns
        patterns = tree.xpath("//*[local-name()='pattern']")
        if not patterns:
            violations.append({'message': "Schematron file contains no patterns.", 'level': 30, 'type': 'Config'})

        # Check rules
        rules = tree.xpath("//*[local-name()='rule']")
        for rule in rules:
            context = rule.get('context')
            if not context:
                violations.append({
                    'message': "Schematron rule missing 'context' attribute.",
                    'level': 40, 'type': 'Config', 'xpath': tree.getpath(rule)
                })
            else:
                # Test XPath context syntax
                try:
                    elementpath.Selector(context, namespaces=STANDARD_NAMESPACES)
                except Exception as e:
                    violations.append({
                        'message': f"Schematron rule context syntax error '{context}': {e}",
                        'level': 40, 'type': 'Config', 'xpath': tree.getpath(rule)
                    })

                # Check undefined elements in schema
                if schema_elements:
                    els, _ = extract_xpath_elements_and_attributes(context)
                    ignored_els = {'Description', 'about', 'href', 'type', 'title'}
                    for el in els:
                        if el not in schema_elements and el not in ignored_els:
                            sugg = get_suggestion(el, schema_elements)
                            violations.append({
                                'message': f"Schematron rule context references element '{el}' "
                                           f"not defined in S1000D XSD schemas.{sugg}",
                                'level': 30, 'type': 'Config', 'xpath': tree.getpath(rule)
                            })

                # Check for undeclared namespaces in context
                clean_str = re.sub(r"'[^']*'", "", context)
                clean_str = re.sub(r'"[^"]*"', "", clean_str)
                prefixes = set(re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*):(?!:)', clean_str))
                for prefix in prefixes:
                    if prefix not in STANDARD_NAMESPACES and prefix not in declared_namespaces:
                        violations.append({
                            'message': f"Schematron rule context contains undeclared namespace prefix '{prefix}'.",
                            'level': 40, 'type': 'Config', 'xpath': tree.getpath(rule)
                        })

        # Check failed-asserts / reports
        asserts = tree.xpath("//*[local-name()='assert'] | //*[local-name()='report']")
        for ass in asserts:
            test = ass.get('test')
            if not test:
                violations.append({
                    'message': "Schematron assert/report missing 'test' attribute.",
                    'level': 40, 'type': 'Config', 'xpath': tree.getpath(ass)
                })
            else:
                try:
                    elementpath.Selector(test, namespaces=STANDARD_NAMESPACES)
                except Exception as e:
                    violations.append({
                        'message': f"Schematron test query syntax error '{test}': {e}",
                        'level': 40, 'type': 'Config', 'xpath': tree.getpath(ass)
                    })

                # Check for undeclared namespaces in test
                clean_str = re.sub(r"'[^']*'", "", test)
                clean_str = re.sub(r'"[^"]*"', "", clean_str)
                prefixes = set(re.findall(r'\b([a-zA-Z_][a-zA-Z0-9_]*):(?!:)', clean_str))
                for prefix in prefixes:
                    if prefix not in STANDARD_NAMESPACES and prefix not in declared_namespaces:
                        violations.append({
                            'message': f"Schematron assert/report test contains undeclared "
                                       f"namespace prefix '{prefix}'.",
                            'level': 40, 'type': 'Config', 'xpath': tree.getpath(ass)
                        })

    except etree.XMLSyntaxError as e:
        violations.append({'message': f"Schematron XML Syntax Error: {e}", 'level': 50, 'type': 'Config'})
    except Exception as e:
        violations.append({'message': f"Schematron Audit Loader Error: {e}", 'level': 50, 'type': 'Config'})

    return violations

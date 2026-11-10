import argparse
import json
import os
import re
import shutil
from pathlib import Path
from lxml import etree

def split_xpath_predicates(pred_str):
    """Splits a predicate string by root-level 'and' operators, respecting nested quotes/brackets."""
    parts = []
    current = []
    br_level = 0
    par_level = 0
    in_single_quote = False
    in_double_quote = False
    i = 0
    n = len(pred_str)
    while i < n:
        c = pred_str[i]
        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        if not in_single_quote and not in_double_quote:
            if c == '[':
                br_level += 1
            elif c == ']':
                br_level -= 1
            elif c == '(':
                par_level += 1
            elif c == ')':
                par_level -= 1
            if br_level == 0 and par_level == 0:
                if i > 0 and i + 3 < n and pred_str[i:i+3].lower() == 'and':
                    if pred_str[i-1] in " \t\r\n" and pred_str[i+3] in " \t\r\n":
                        parts.append("".join(current).strip())
                        current = []
                        i += 4  # skip 'and' and the following whitespace
                        continue
        current.append(c)
        i += 1
    if current:
        parts.append("".join(current).strip())
    return parts

def clean_xpath_path(p):
    """Cleans leading dot/slash from a relative path segment."""
    p = p.strip()
    if p.startswith("./"):
        p = p[2:]
    elif p.startswith("/"):
        p = p[1:]
    return p

def get_matching_bracket_index(s, open_idx):
    br_level = 0
    in_single_quote = False
    in_double_quote = False
    for i in range(open_idx, len(s)):
        c = s[i]
        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        if not in_single_quote and not in_double_quote:
            if c == '[':
                br_level += 1
            elif c == ']':
                br_level -= 1
                if br_level == 0:
                    return i
    return -1

def has_root_level_comparison(s):
    """Checks if there is a comparison operator (=, !=, <, >) at the root level of the string (outside brackets/parens)."""
    br_level = 0
    par_level = 0
    in_single_quote = False
    in_double_quote = False
    for i in range(len(s)):
        c = s[i]
        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
        if not in_single_quote and not in_double_quote:
            if c == '[':
                br_level += 1
            elif c == ']':
                br_level -= 1
            elif c == '(':
                par_level += 1
            elif c == ')':
                par_level -= 1
            if br_level == 0 and par_level == 0:
                if s[i:i+2] in ("!=", "<=", ">="):
                    return True
                if c in ("=", "<", ">") and s[i-1] not in ("!", "<", ">") and s[i+1] not in ("="):
                    return True
    return False

def is_simple_path(s):
    """Returns True if the string is a simple node selection path (no functions/comparisons)."""
    return bool(re.match(r'^[\w\-.:@/*\s]+$', s))

def refactor_xpath(path_str, flag, use_text):
    """
    Refactors XPath starting with /root[...] to point directly to the painpoint.
    Returns (refactored_xpath, status_msg).
    """
    path_str = re.sub(r'\s+', ' ', path_str.strip())
    
    # Match /(dmodule|pm|ddn|dml|comment)[
    match_root = re.match(r'^/([a-zA-Z0-9_:-]+)\[', path_str)
    if not match_root:
        return path_str, "Skipped: does not start with root element predicate"
        
    root_tag = match_root.group(1)
    open_idx = len(root_tag) + 2  # length of "/root_tag["
    
    # Verify if the outermost brackets wrap the entire string
    matching_idx = get_matching_bracket_index(path_str, open_idx - 1)
    if matching_idx != len(path_str) - 1:
        return path_str, f"Skipped: /{root_tag}[...] predicate does not wrap the entire path"
        
    # Extract inner predicate content
    pred_str = path_str[open_idx:-1].strip()
    conjuncts = split_xpath_predicates(pred_str)
    
    if len(conjuncts) == 1:
        # --- SIMPLE RULE (1 conjunct) ---
        c = conjuncts[0]
        # Check if it is a missing element check: not(PATH) or empty(PATH)
        match_not = re.match(r'^(?:not|empty)\((.*?)\)$', c)
        if match_not:
            inner_path = match_not.group(1).strip()
            # If the inner expression contains comparisons or functions at root level, do not refactor to node selection!
            if has_root_level_comparison(inner_path) or not is_simple_path(inner_path):
                return f"/{root_tag}[{c}]", "Skipped: inner comparison or complex expression in not/empty check"
                
            inner_path_clean = clean_xpath_path(inner_path)
            parts = inner_path_clean.split('/')
            if len(parts) > 1:
                parent_path = "/".join(parts[:-1])
                child = parts[-1]
                return f"/{root_tag}/{parent_path}[not({child})]", "Refactored simple not/empty rule"
            else:
                return f"/{root_tag}[not({inner_path_clean})]", "Simple not/empty rule (no parent split)"
        else:
            # Just remove the brackets
            c_clean = clean_xpath_path(c)
            return f"/{root_tag}/{c_clean}", "Refactored simple presence rule"
            
    else:
        # --- COMPOUND RULE (2+ conjuncts) ---
        # Separate preconditions from the violation check
        preconditions = []
        violations = []
        
        for c in conjuncts:
            c_clean = c.strip()
            
            # Heuristic for precondition checks:
            is_precond = False
            
            # Matches content schema type checks: content/illustratedPartsCatalog, content/sb, etc.
            if re.search(r'\bcontent/(illustratedPartsCatalog|sb|container|description|procedure|faultIsolation|faultReporting|crew|maintPlanning)\b', c_clean):
                is_precond = True
            elif re.search(r'\b(issueNumber|inWork|languageIsoCode|countryIsoCode)\b', c_clean):
                is_precond = True
            elif c_clean.startswith("./identAndStatusSection/") or c_clean.startswith("identAndStatusSection/"):
                is_precond = True
            elif c_clean.startswith("empty(./content/container)") or c_clean.startswith("not(./content/container)"):
                is_precond = True
            elif "@infoCode" in c_clean or "@systemCode" in c_clean or "@modelIdentCode" in c_clean:
                is_precond = True
                
            if is_precond:
                preconditions.append(c_clean)
            else:
                violations.append(c_clean)
                
        # If all conjuncts were classified as precondition, last one is violation
        if not violations:
            violations = [preconditions.pop()]
            
        # Process violation conjuncts.
        # If a violation cannot be refactored into a valid path step, we demote it to a precondition!
        refactored_violations = []
        for v in violations:
            # 1. not(func(PATH, VALUE)) -> PATH[not(func(., VALUE))]
            match_func = re.match(r'^not\((ends-with|starts-with|contains|matches)\((.*?),[ \t]*(.*?)\)\)$', v)
            if match_func:
                func_name = match_func.group(1)
                path_arg = match_func.group(2).strip()
                val_arg = match_func.group(3).strip()
                path_arg_clean = clean_xpath_path(path_arg)
                refactored_violations.append(f"{path_arg_clean}[not({func_name}(., {val_arg}))]")
                continue
                
            # 2. func(PATH, VALUE) -> PATH[func(., VALUE)]
            match_func_pos = re.match(r'^(ends-with|starts-with|contains|matches)\((.*?),[ \t]*(.*?)\)$', v)
            if match_func_pos:
                func_name = match_func_pos.group(1)
                path_arg = match_func_pos.group(2).strip()
                val_arg = match_func_pos.group(3).strip()
                path_arg_clean = clean_xpath_path(path_arg)
                refactored_violations.append(f"{path_arg_clean}[{func_name}(., {val_arg})]")
                continue

            # 3. empty(PATH) or not(PATH) -> select parent, predicate child
            match_not = re.match(r'^(?:not|empty)\((.*?)\)$', v)
            if match_not:
                inner = match_not.group(1).strip()
                if has_root_level_comparison(inner) or not is_simple_path(inner):
                    # Demote to precondition
                    preconditions.append(v)
                else:
                    inner_clean = clean_xpath_path(inner)
                    parts = inner_clean.split('/')
                    if len(parts) > 1:
                        parent = "/".join(parts[:-1])
                        child = parts[-1]
                        refactored_violations.append(f"{parent}[not({child})]")
                    else:
                        refactored_violations.append(f"[not({inner_clean})]")
                continue
                
            # 4. not(PATH = VALUE) -> PATH[not(. = VALUE)]
            if v.startswith("not(") and ("=" in v or "!=" in v) and v.endswith(")"):
                inner = v[4:-1].strip()
                if has_root_level_comparison(inner):
                    preconditions.append(v)
                else:
                    parts = re.split(r'(=|!=)', inner)
                    if len(parts) >= 3:
                        left = parts[0].strip()
                        op = parts[1].strip()
                        right = "".join(parts[2:]).strip()
                        left_clean = clean_xpath_path(left)
                        if op == "=":
                            refactored_violations.append(f"{left_clean}[not(.{op}{right})]")
                        else:
                            refactored_violations.append(f"{left_clean}[.{op}{right}]")
                    else:
                        preconditions.append(v)
                continue
                
            # 5. PATH = VALUE -> PATH[. = VALUE]
            if "=" in v and not v.startswith("not("):
                parts = re.split(r'(=|!=)', v)
                if len(parts) >= 3:
                    left = parts[0].strip()
                    op = parts[1].strip()
                    right = "".join(parts[2:]).strip()
                    left_clean = clean_xpath_path(left)
                    refactored_violations.append(f"{left_clean}[.{op}{right}]")
                else:
                    preconditions.append(v)
                continue
                
            # 6. Default presence check: select path
            refactored_violations.append(clean_xpath_path(v))
            
        precond_str = " and ".join(preconditions)
        violation_str = "/".join(refactored_violations)
        
        if precond_str and violation_str:
            return f"/{root_tag}[{precond_str}]/{violation_str}", "Refactored compound rule"
        elif violation_str:
            return f"/{root_tag}/{violation_str}", "Refactored compound rule (no precond)"
        else:
            return f"/{root_tag}[{precond_str}]", "Refactored compound rule (all precond/demoted)"

def is_valid_value_list(s):
    """Checks if a string is a simple comma-separated list of quoted string literals or digits."""
    parts = s.split(',')
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Must match a quoted string literal (no internal unescaped quotes/syntax) or digit
        if not (re.match(r'^([\'"])[^\'"]*\1$', p) or p.isdigit()):
            return False
    return True

def extract_values_and_refactor(path, flag):
    """
    Checks if path has an embedded value list check, and refactors it to use objectValue.
    Returns (refactored_path, refactored_flag, list_of_values) if matched, else (path, flag, None).
    """
    path = path.strip()
    
    # 1. Matches: PATH[not(string()=(VALUES))] or PATH[not(. = (VALUES))]
    match1 = re.search(r'\[not\((?:\.|string\(\))\s*=\s*\(([^\[\]]*?)\)\)\]$', path)
    if match1:
        val_str = match1.group(1)
        if is_valid_value_list(val_str):
            vals = [v.strip().strip("'\"") for v in val_str.split(',')]
            new_path = path[:match1.start()]
            return new_path, "2", vals

    # 2. Matches: PATH[not(@attr = (VALUES))]
    match2 = re.search(r'\[not\((@[a-zA-Z0-9_:-]+)\s*=\s*\(([^\[\]]*?)\)\)\]$', path)
    if match2:
        attr = match2.group(1)
        val_str = match2.group(2)
        if is_valid_value_list(val_str):
            vals = [v.strip().strip("'\"") for v in val_str.split(',')]
            new_path = path[:match2.start()] + "/" + attr
            return new_path, "2", vals

    # 3. Matches: PATH[@attr = (VALUES)] (without not)
    # We only convert positive checks to allowed values (flag 2) if the original flag was NOT "0" (forbidden)
    if flag != "0":
        match3 = re.search(r'\[(@[a-zA-Z0-9_:-]+)\s*=\s*\(([^\[\]]*?)\)\]$', path)
        if match3:
            attr = match3.group(1)
            val_str = match3.group(2)
            if is_valid_value_list(val_str):
                vals = [v.strip().strip("'\"") for v in val_str.split(',')]
                new_path = path[:match3.start()] + "/" + attr
                return new_path, "2", vals

    # 4. Matches: PATH[not(text() = (VALUES))]
    match4 = re.search(r'\[not\(text\(\)\s*=\s*\(([^\[\]]*?)\)\)\]$', path)
    if match4:
        val_str = match4.group(1)
        if is_valid_value_list(val_str):
            vals = [v.strip().strip("'\"") for v in val_str.split(',')]
            new_path = path[:match4.start()]
            return new_path, "2", vals
        
    return path, flag, None

def run_consistency_check(rid, path, use_text):
    """
    Checks consistency between description text and XPath rule.
    Returns list of warnings.
    """
    warnings = []
    use_lower = use_text.lower()
    path_lower = path.lower()
    
    # 1. Check Info Codes (e.g. "0B1", "0B2", "933", "000")
    info_codes = re.findall(r'\b(?:info|information)\s+code\s+["\']?([0-9][0-9a-z]{2})["\']?', use_lower)
    for code in info_codes:
        if code not in path_lower:
            warnings.append(f"Info code '{code}' mentioned in description but not found in XPath.")
            
    # 2. Check SNS / System Codes (e.g. "04-10", "04-20", "05-10")
    sns_codes = re.findall(r'\b\d{2}-\d{2}\b', use_lower)
    for sns in sns_codes:
        sns_clean = sns.replace('-', '')
        if sns not in path_lower and sns_clean not in path_lower:
            warnings.append(f"SNS code '{sns}' mentioned in description but not found in XPath.")
            
    # 3. Check Element names in description (e.g. <enterpriseName>, <responsiblePartnerCompany>)
    elements = re.findall(r'<([a-zA-Z0-9_:-]+)>', use_lower)
    for el in elements:
        # Skip standard generic S1000D elements that might be implied
        if el in ['dmodule', 'content', 'element', 'attribute']:
            continue
        if el not in path_lower:
            warnings.append(f"Element name '<{el}>' mentioned in description but not found in XPath.")
            
    # 4. Check Attribute names in description (e.g. enterpriseCode, updateReasonType)
    attrs = re.findall(r'\battribute\s+([a-zA-Z0-9_:-]+)\b', use_lower)
    for attr in attrs:
        if attr not in path_lower:
            warnings.append(f"Attribute '{attr}' mentioned in description but not found in XPath.")
            
    return warnings

# Optional user-supplied rule mappings (e.g. loaded via --corrections-map)
CORRECTED_PATHS = {}

def main():
    base_dir = Path(__file__).resolve().parent
    default_dest = base_dir / "config"
    
    parser = argparse.ArgumentParser(description="Refactor and audit S1000D BREX XML rules")
    parser.add_argument("--src-dir", type=Path, default=None, help="Source directory containing BREX XMLs (defaults to config)")
    parser.add_argument("--dest-dir", type=Path, default=default_dest, help="Destination directory for refactored BREX")
    parser.add_argument("--corrections-map", type=Path, default=None, help="Optional JSON file mapping rule IDs to [path, flag] overrides")
    args = parser.parse_args()

    dest_dir = args.dest_dir.resolve()
    src_dir = args.src_dir.resolve() if args.src_dir else dest_dir

    if args.corrections_map and args.corrections_map.exists():
        try:
            with open(args.corrections_map, "r", encoding="utf-8") as cm_f:
                loaded_map = json.load(cm_f)
                for k, v in loaded_map.items():
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        CORRECTED_PATHS[k] = (str(v[0]), str(v[1]))
            print(f"Loaded {len(CORRECTED_PATHS)} custom rule corrections from {args.corrections_map.name}.")
        except Exception as ex:
            print(f"Warning: Failed to load corrections map: {ex}")

    if not src_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")

    is_in_place = (src_dir == dest_dir)
    
    if not is_in_place:
        # Preserve any existing Schematron (.sch) files in dest_dir before recreating it
        preserved_sch = {}
        if dest_dir.exists():
            for sch_f in dest_dir.glob("*.sch"):
                preserved_sch[sch_f.name] = sch_f.read_bytes()
            shutil.rmtree(dest_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)
        for sch_name, sch_bytes in preserved_sch.items():
            (dest_dir / sch_name).write_bytes(sch_bytes)
        
        # Copy other folders (schemas, schxslt, validator_settings.json, and .sch files)
        for entry in src_dir.iterdir():
            if entry.is_dir() and entry.name in ("schemas", "schxslt"):
                shutil.copytree(entry, dest_dir / entry.name)
            elif entry.is_file() and (entry.name == "validator_settings.json" or entry.suffix.lower() == ".sch"):
                shutil.copy2(entry, dest_dir / entry.name)
            
    xml_files = list(src_dir.glob("*.xml"))
    print(f"Refactoring and auditing {len(xml_files)} BREX XML files...")
    
    total_rules = 0
    refactored_count = 0
    value_extracted_count = 0
    total_warnings = 0
    
    for f_path in xml_files:
        print(f"\nProcessing {f_path.name}...")
        
        # Load and parse
        parser = etree.XMLParser(remove_blank_text=False)
        tree = etree.parse(str(f_path), parser=parser)
        
        # Clean up stray commas/character content under structureObjectRuleGroup elements (schema validation fix)
        for group in tree.xpath("//*[local-name()='structureObjectRuleGroup']"):
            if group.text and group.text.strip():
                group.text = group.text.strip().replace(',', '')
            for child in group:
                if child.tail and child.tail.strip():
                    child.tail = child.tail.strip().replace(',', '')
                    if not child.tail:
                        child.tail = None
                        
        rules = tree.xpath("//*[local-name()='structureObjectRule']")
        
        file_rules = 0
        file_refactored = 0
        file_warnings = 0
        
        for rule in rules:
            file_rules += 1
            total_rules += 1
            
            rid = rule.get("id") or "GENERIC"
            p_els = rule.xpath(".//*[local-name()='objectPath']")
            u_els = rule.xpath(".//*[local-name()='objectUse']")
            
            if not p_els or not p_els[0].text:
                continue
                
            path = p_els[0].text.strip()
            use = u_els[0].text.strip() if u_els and u_els[0].text else ""
            flag = p_els[0].get("allowedObjectFlag") or "2"
            
            # Direct mapping for known broken rules
            if rid in CORRECTED_PATHS:
                new_path, ref_flag = CORRECTED_PATHS[rid]
                p_els[0].text = new_path
                p_els[0].set("allowedObjectFlag", ref_flag)
                
                # Remove any existing objectValue elements
                for ov in rule.xpath(".//*[local-name()='objectValue']"):
                    rule.remove(ov)
                
                file_refactored += 1
                refactored_count += 1
                continue
                
            # 1. Consistency check
            warns = run_consistency_check(rid, path, use)
            for w in warns:
                file_warnings += 1
                total_warnings += 1
                print(f"  [CONSISTENCY WARNING] Rule {rid}: {w}")
                
            # 2. Refactoring XPath
            new_path = path
            if path.startswith(("/dmodule[", "/pm[", "/ddn[", "/dml[", "/comment[")):
                new_path, msg = refactor_xpath(path, flag, use)
                
            # 3. ObjectValue Extraction and Conversion
            ref_path, ref_flag, vals = extract_values_and_refactor(new_path, flag)
            if vals:
                # Update rule path and flag
                p_els[0].text = ref_path
                p_els[0].set("allowedObjectFlag", ref_flag)
                
                # Remove any existing objectValue elements
                for ov in rule.xpath(".//*[local-name()='objectValue']"):
                    rule.remove(ov)
                    
                # Append new objectValue elements in the correct schema order (after objectUse)
                for val in vals:
                    ov_el = etree.Element("objectValue")
                    ov_el.set("valueForm", "single")
                    ov_el.set("valueAllowed", val)
                    rule.append(ov_el)
                    
                file_refactored += 1
                value_extracted_count += 1
                refactored_count += 1
            elif new_path != path:
                p_els[0].text = new_path
                file_refactored += 1
                refactored_count += 1
                
        # Save refactored XML to destination
        dest_path = dest_dir / f_path.name
        tree.write(str(dest_path), encoding="utf-8", xml_declaration=True)
        print(f"  Rules: {file_rules} | Refactored: {file_refactored} | Warnings: {file_warnings} -> Saved to {dest_path.name}")
        
        # Sync to test_suite/config/
        test_dest_dir = base_dir / "test_suite" / "config"
        if test_dest_dir.exists() and test_dest_dir.resolve() != dest_dir.resolve():
            shutil.copy2(dest_path, test_dest_dir / f_path.name)
            
    print("\n" + "="*50)
    print("REFACTORING SUMMARY")
    print("="*50)
    print(f"Total Rules processed:       {total_rules}")
    print(f"Rules Refactored:            {refactored_count}")
    print(f"Rules converted to value list: {value_extracted_count}")
    print(f"Total Consistency Warnings:  {total_warnings}")
    print(f"Output directory:            {dest_dir}")
    print("="*50)

if __name__ == "__main__":
    main()

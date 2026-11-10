# S1000D XML Validation Suite — Audit & Way Ahead Requirements Document

**Current Version Evaluated:** `v8.6.1` (Viewer `v8.9.0`, GUI `v8.2`, Package `v8.5.1`)  
**Date:** 2026-10-16  
**Scope:** Core Validation Engines, CLI/Configuration, Desktop GUI, HTML Summary Report, Analyst Workspace Viewer, Test Suite, and Repository Architecture.

---

## 1. Executive Summary

The **S1000D XML Validation Suite** has evolved into a fast, modular validation pipeline leveraging **SaxonC (`saxonche`)** for XPath 3.1 / XSLT 2.0+ evaluation, **`lxml`** for W3C XSD validation and sourceline synchronization, and **live SQLite WAL streaming** for low-memory batch execution. The Conformance Test Suite (`run_test_suite.py`) passes all 6 scenarios (24 manifest test cases + chain/audit/discovery checks) in ~15 seconds.

However, a deep code and UX inspection revealed **8 functional bugs/inconsistencies**, **significant feature drift in the Desktop GUI**, **offline/CORS limitations in the HTML Viewer**, and **key S1000D domain expansion opportunities** (CSDB external manifests, internal reference validation, applicability cross-checks, and notation rules).

> [!IMPORTANT]
> The most critical functional bug is that **non-error severities (`WARNING` / `INFO`) still mark files as `invalid` and trigger a non-zero exit code (`1`)**, breaking CI/CD pipelines whenever default Integrity warnings occur, while `INFO`-level findings are dropped from the database yet counted as invalid.

---

## 2. Identified Bugs & Technical Issues

### 2.1 Critical & High-Severity Bugs

| ID | Component | Location | Issue Description | Impact |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-01** | Core / CLI | `s1000d_validator/core.py` (L571–774)<br>`s1000d_validator/cli.py` (L643–648) | **Severity vs. File Validity Mismatch:** Every engine sets `status['status'] = 'invalid'` regardless of whether the configured severity is `ERROR` (40), `WARNING` (30), or `INFO` (20). In `cli.py` (L778–780), any `invalid` file triggers `sys.exit(1)`, contradicting `specification.md`. Furthermore, `INFO` (level 20) logs are filtered out before DB insertion (`cli.py` L696), causing files with only `INFO` findings to be counted as `invalid` in the summary while appearing in the `"Valid Files"` tab of the Viewer (`WHERE l.id IS NULL`). | **Critical** — Breaks CI/CD exit code contract and corrupts Valid/Invalid counts. |
| **BUG-02** | Reporting / Viewer | `s1000d_validator/reporting.py` (L315–318)<br>`S1000D_App_Viewer.html` (L783–789) | **Broken "Open Analyst Workspace" Deep Link:**<br>1. `openViewer()` hardcodes `../S1000D_App_Viewer.html?db=logs/{db_filename}`, which fails whenever `-l / --log-dir` is customized (e.g., nested folders or absolute paths).<br>2. When opened locally via `file://`, modern browsers block `fetch(db)` due to CORS policy on local files. The empty `catch(e) {}` in `S1000D_App_Viewer.html` (L788) silently swallows the error, stranding the user on the Launchpad. | **High** — Primary workflow from Summary Report (`Method 1`) silently fails in local browsers. |
| **BUG-03** | Viewer / Reporting | `S1000D_App_Viewer.html` (L8–10, L484) | **External CDN Dependency in "Offline" Viewer:** Despite documentation stating the Viewer is 100% offline, it fetches `sql-wasm.js`, `sql-wasm.wasm`, `chart.js`, and Google Fonts from internet CDNs. In air-gapped defense/aerospace networks, `initSqlJs()` fails completely. | **High** — Unusable in restricted/offline corporate or military networks. |
| **BUG-04** | Config / Tooling | `refactor_brex.py` (L418–427) | **Schematron File Deleted from `config/`:** `refactor_brex.py` deletes `config/` via `shutil.rmtree()` and copies `schemas/`, `schxslt/`, `validator_settings.json`, and `*.xml`, omitting `*.sch`. As a result, `config/S1000D_Business_Rules.sch` is missing from the main `config/` folder (only present in `test_suite/config/`). | **High** — Running the validator with `-c ./config` silently skips Schematron rules. |

### 2.2 Medium & Low-Severity Bugs

| ID | Component | Location | Issue Description | Impact |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-05** | Reporting | `s1000d_validator/reporting.py` (L196–201, L335–352) | **Missing Schematron & Naming Bars in Summary HTML:** `write_html_report()` computes percentages for Syntax, Schema, BREX, Resource, Reference, and Config, but omits `by_schematron` and `by_naming`. Also, percentages use `inv` (invalid files) as denominator while a file can fail multiple categories (summing > 100%) or `by_config` can be non-zero when `inv == 0`. | **Medium** — Misleading visual summary report. |
| **BUG-06** | BREX Engine | `s1000d_validator/engines.py` (L161–173) | **Hardcoded Severity on Mandatory BREX Rules:** When `allowedObjectFlag == "1"` fails (mandatory node missing), `Violation` is created with hardcoded `level=40` instead of reading `self.config.get("brex_severity", "ERROR")`. | **Medium** — Ignores `validator_settings.json` severity override for flag `1` rules. |
| **BUG-07** | CLI / DB | `s1000d_validator/cli.py` (L613–615) | **Config Audit Levelname Hardcoded as `'ERROR'`:** Dead-rule warnings (`level=30`) found during static BREX/Schematron auditing are inserted into the `Errors` table with `levelname='ERROR'` instead of `'WARNING'`. | **Low** — Config warnings appear as red `ERROR` badges in the Viewer. |
| **BUG-08** | Baseline Suppression | `s1000d_validator/core.py` (L351–371)<br>`s1000d_validator/engines.py` (L49–64) | **Duplicate & Inconsistent `is_suppressed()` Logic:** `core.py` uses case-sensitive regexes while `engines.py` uses `re.I`. Neither supports matching by `rule_id`, which is the primary identifier S1000D authors use to suppress rules. | **Medium** — Inconsistent suppression behavior across engines. |

---

## 3. User Experience (UX) Evaluation

### 3.1 Analyst Workspace (`S1000D_App_Viewer.html`)
1. **Charts Do Not React to Filters (L689–718):**
   - The Help modal states: *"Charts update in real-time based on your current filters."*
   - In reality, `renderInsights()` aggregates `DATA_RAW` instead of `FILTERED_INDICES`, and `applyAllFilters()` does not re-render charts when the Insights tab is active.
2. **Missing "Reset Filters" Action & Active Filter Indicators:**
   - `resetFilters()` is defined at L757 but has **no button bound to it** in the DOM.
   - Because all 6 sidebar facet categories default to `collapsed`, active filters are hidden when groups are collapsed.
3. **Unpaginated DOM Render on "Valid Files" Tab (L739–753):**
   - `renderValidFiles()` renders every valid file into the DOM at once without pagination, sorting, or Omni-Search filtering. On a 20,000+ DM batch, this tab will freeze the browser.
4. **Confusing KPI Metrics (L208–213, L720–726):**
   - `Violation Rate` divides filtered `ERROR`-level rows by total `DATA_RAW` error rows, rather than showing **Invalid DMs / Total DMs (%)**.
   - Total DMs and Invalid DMs counts are not shown in the KPI bar.
5. **Diagnostics Drawer UX (L678–687):**
   - Lacks quick-action buttons: **Copy XPath**, **Copy DMC**, **Copy Filename**, or **Copy Baseline Ignore JSON Snippet** (so users can easily add a false positive to `baseline.json`).

### 3.2 Desktop GUI (`s1000d_validator/gui.py`)
The Tkinter GUI (`gui.py`) has fallen behind the CLI capabilities (`v8.2` vs `v8.6.1`):
- **Missing Dependency Check:** `verify_libs()` checks `lxml` and `elementpath` but omits `saxonche`.
- **Missing Controls:** Cannot configure BREX mode (`project`, `chain`, `ignore`), Schema mode (`auto`, `local`, `online`), Allowed S1000D Versions, Engine Toggles (Schema, BREX, Schematron, Integrity, Resource Checks), Strict Config, or CSV export.
- **No Stop/Cancel Button:** Users cannot abort a running validation job without closing the entire GUI window.
- **No Post-Run Action Buttons:** No button to directly open the generated HTML Report or launch the Analyst Workspace upon completion.
- **No History Persistence:** Does not read or write `.validator_history.json`.
- **Console Progress Bar Rendering:** `cli.py` uses `\r` carriage returns to animate the progress bar in terminal stdout, which causes Tkinter's `tk.Text` widget to buffer and dump a massive single line of repeated progress bars.

---

## 4. Architecture, Performance & S1000D Coverage Opportunities

1. **Eliminate Redundant XML Parsing:**
   - Currently, each XML file is parsed from disk by `lxml` (`core.py` L446) and parsed from disk a second time by `saxonche` (`core.py` L457). Furthermore, if Saxon is only needed when BREX or Schematron is active, `saxon_doc` should not be built when `--no-brex --no-sch` are set.
2. **Dynamic Chunksize in Multiprocessing Pool:**
   - `README.md` claims *"chunk sizes are dynamically adjusted to maximize parallel core utilization"*, but `cli.py` (L634) hardcodes `chunksize=10`. Dynamic chunk sizing (`max(1, min(50, total_files // (workers * 4)))`) will improve both small and huge batch speeds.
3. **S1000D Domain Completeness:**
   - **BREX `<notationRuleList>` Support:** S1000D BREX modules define allowed NOTATION declarations (`<notationRule>`). Currently only `<structureObjectRule>` is parsed.
   - **BREX Context Resolution:** Support `<contextRules>` without `@rulesContext` explicitly as universal rules across all S1000D schemas, and support URN-style `@rulesContext` values.
   - **Schematron Rule ID Granularity:** Extract `@id` from `<sch:assert>` / `<sch:report>` / `<sch:rule>` in SVRL (`svrl:failed-assert/@id`, `preceding-sibling::svrl:fired-rule[1]/@id`) before falling back to `svrl:active-pattern/@id`.
   - **Extended Integrity Checks:**
     - Support `<pmRef>` (Publication Module references) and PMC/DML/DDN/COM file discovery.
     - Support **External CSDB Inventory / Manifest (`--csdb-manifest`)** so partial deliveries can validate `<dmRef>` and ICNs against known master CSDB holdings without false positives.
     - Optional **DMC Fuzzy Suggestion** (using `difflib`, similar to `audit.py`) when a broken `<dmRef>` closely matches an existing DM in the package.
4. **Repository & Packaging Hygiene:**
   - Synchronize version numbers (`pyproject.toml`, `cli.py`, `gui.py`, `README.md`, `S1000D_App_Viewer.html`) via a single `__version__` constant in `s1000d_validator/__init__.py`.
   - Clean up legacy directories, zip archives in root, and unstaged Git deletions.

---

## 5. Way Ahead Requirements Document (Roadmap v8.7 – v9.0)

### Phase 1: Core Reliability, Bug Fixes & Config Integrity (`v8.7.0`)

| Req ID | Priority | Status | Requirement Specification | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-101** | **P0** | ✅ Implemented | **Decouple File Validity from Non-Error Severities:** A Data Module shall only be marked `invalid` (and trigger CLI exit code `1`) if it has at least one unsuppressed violation with `level >= 40` (`ERROR`). Files with only `WARNING` (30) or `INFO` (20) findings shall be classified as `valid` and exit with code `0` (unless `--fail-on-warning` is specified). | Running validation where only `WARNING`-level Integrity issues exist exits with code `0`; `INFO` (level 20) records are persisted to SQLite `Errors`/`Locations` so they are inspectable in the Viewer. |
| **REQ-102** | **P0** | ✅ Implemented | **Unify Severity & Suppression Handling:** `SaxonBrexEngine` flag `"1"` violations must respect `brex_severity`. `CONFIG_AUDIT` DB entries must map `level=30` to `levelname='WARNING'`. Consolidate `is_suppressed()` into a single function supporting regex matching on `rule_id`, `error_type`, `dm_code`, `xpath`, and `message`. | Unit/manifest tests verify `rule_id` baseline suppression and severity overrides across all 4 engines. |
| **REQ-103** | **P0** | ✅ Implemented | **Restore Schematron in `config/` & Fix `refactor_brex.py`:** Update `refactor_brex.py` to preserve `*.sch` files when rebuilding `config/`, and restore `S1000D_Business_Rules.sch` to `config/`. | `config/S1000D_Business_Rules.sch` exists and is preserved across `refactor_brex.py` runs. |
| **REQ-104** | **P1** | ✅ Implemented | **Dynamic Multiprocessing Chunk Sizing & Lazy Saxon Parsing:** Compute `chunksize` dynamically from `total_files` and `max_workers`. Only invoke `GLOBAL_SAXON_BUILDER.parse_xml()` when BREX or Schematron engines are active for the current run. | 24-file test suite utilizes all available CPU workers (`chunksize=1`); `--no-brex --no-sch` runs skip Saxon parsing completely. |
| **REQ-105** | **P1** | ✅ Implemented | **Single Source of Truth for Versioning:** Define `__version__ = "8.7.0"` in `s1000d_validator/__init__.py` and reference it across CLI, GUI, `pyproject.toml`, and generated reports. | `--version` flag works in CLI; all UI titles and reports display the unified version. |

---

### Phase 2: Analyst Viewer & Desktop GUI Modernization (`v8.8.0`)

| Req ID | Priority | Status | Requirement Specification | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-201** | **P0** | ✅ Implemented | **Seamless Local DB Bridge & Full Summary Bars:**<br>1. In `write_html_report()`, compute relative paths dynamically and embed a Base64 `postMessage` bridge (`S1000D_REQUEST_DB` / `S1000D_DB_PAYLOAD`) so clicking "Open Analyst Workspace" works over `file://` without CORS failure.<br>2. Fix `ERROR` badge styling in `S1000D_App_Viewer.html`.<br>3. Include `Schematron` and `Naming` bars in the Summary HTML Report. | Opening `YYYY-MM-DD_report.html` from any custom `-l` directory accurately displays all 8 error categories and loads the workspace over `file://`. |
| **REQ-202** | **P1** | ✅ Implemented | **Filter-Reactive Insights & Filter Management in Viewer:**<br>1. Update `renderInsights()` in `S1000D_App_Viewer.html` to aggregate over `FILTERED_INDICES` instead of `DATA_RAW`.<br>2. Add **"Reset Filters"** buttons and display active filter badges/counts on collapsed facet headers.<br>3. Add pagination and Omni-Search support to the **"Valid Files"** tab.<br>4. Display accurate file-level KPI failure rate and preserve warning-only files in `Valid Files`. | Toggling any sidebar filter immediately updates charts on the "Analysis Summary" tab; clicking "Reset Filters" clears all tri-state filters and search queries. |
| **REQ-203** | **P1** | ✅ Implemented | **Diagnostics Drawer Quick Actions:** In the `#details-pane` drawer of `S1000D_App_Viewer.html`, add one-click buttons to **Copy DMC**, **Copy XPath**, and **Copy Baseline Rule JSON** (pre-filled with `error_type`, `rule_id`, `dm_code`, `xpath`). | Clicking "Copy Baseline Rule JSON" copies a valid JSON object ready to paste into `baseline.json`. |
| **REQ-204** | **P1** | ✅ Implemented | **GUI v8.7.0 Feature Parity & Process Control:** Upgrade `gui.py` to:<br>- Verify `saxonche` in `verify_libs()`.<br>- Persist/load settings from `.validator_history.json`.<br>- Expose Engine Toggles, BREX Mode, Schema Mode, CSDB Manifest, CSV, JUnit XML, and SARIF exports.<br>- Add a **"⏹ Stop"** button, **"📊 Open Latest Report"** button, and native `ttk.Progressbar`. | Users can configure all major CLI options from the GUI, see a native progress bar, stop a running batch cleanly, and open the HTML report in one click. |

---

### Phase 3: S1000D Domain Expansion (`v8.9.0`)

| Req ID | Priority | Status | Requirement Specification | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-301** | **P1** | ✅ Implemented | **Granular Schematron Rule IDs:** In `SaxonSchematronEngine`, extract rule IDs using priority order: `svrl:failed-assert/@id` -> `preceding-sibling::svrl:fired-rule[1]/@id` -> `preceding-sibling::svrl:active-pattern[1]/@id` -> Schematron filename. | Schematron assertions with `@id` attributes report their specific assertion ID in the `Rule ID` column. |
| **REQ-302** | **P1** | ✅ Implemented | **External CSDB Manifest & Extended Link Integrity:**<br>1. Add `--csdb-manifest <path>` accepting a TXT/CSV/JSON list of existing DMCs, PMCs, and ICNs in the master CSDB.<br>2. Register config-directory BREX DMCs into `available_dmcs`.<br>3. Extend `IntegrityEngine` to validate `<pmRef>` (`PM_LINK_BROKEN`) and internal `<internalRef internalRefId="...">` targets (`INTERNAL_LINK_BROKEN`).<br>4. Provide fuzzy-match suggestions (`Did you mean: DMC-...?`) when a `<dmRef>` fails resolution. | Partial supplier deliveries validated with `--csdb-manifest` produce zero false-positive `LINK_BROKEN` or `RES_MISSING` errors for master CSDB assets. |
| **REQ-303** | **P2** | ✅ Implemented | **BREX `<notationRuleList>` & URN Context Support:** Extend BREX parser and engine to validate `<notationRule>` constraints against XML `<!NOTATION ...>` declarations and support URN/universal `<contextRules>`. | BREX notation rules and URN contexts are parsed and enforced during validation. |
| **REQ-304** | **P2** | 📋 Planned | **Applicability Cross-Reference Validation (ACT/CCT/PCT):** Optional integrity stage that resolves `<applicRef>` / `<applic>` `applicPropertyIdent` and `applicPropertyType` values against the referenced ACT, CCT, and PCT data modules in the dataset. | Invalid applicability property IDs or out-of-range values are flagged with `APPLIC_INVALID`. |

---

### Phase 4: Enterprise CI/CD & Repository Hygiene (`v9.0.0`)

| Req ID | Priority | Status | Requirement Specification | Acceptance Criteria |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-401** | **P1** | ✅ Implemented | **JUnit XML & SARIF Output Formats:** Add `--junit` and `--sarif` export flags so GitLab CI, GitHub Actions, and Azure DevOps can render inline S1000D validation annotations directly on Pull Requests and pipeline test tabs. | CI/CD runners natively parse the JUnit/SARIF output and display rule violations per file and line number. |
| **REQ-402** | **P2** | ✅ Implemented (Scenario 7) | **Automated Conformance Suite Expansion:** Extend `run_test_suite.py` with Scenario 7 covering warning exit codes, `--csdb-manifest`, `INTERNAL_LINK_BROKEN`, `rule_id` baseline suppression, JUnit XML, and SARIF v2.1.0 generation. | `python run_test_suite.py` executes all 7 conformance scenarios with 0 failures. |
| **REQ-403** | **P2** | ✅ Implemented | **Repository Hygiene & Legacy Purge:** Remove legacy duplicate folders and root binary archives (`.zip`), configure `.gitignore` for archives and build artifacts, update `refactor_brex.py` to support dynamic paths with fallback to `config/`. | Repository contains zero obsolete config clones or untracked zip files; `git status` is clean; remote repository on HomeShare is synchronized. |


## [Unreleased]
- Keep warning-only files valid when `--fail-on-warning` is enabled; apply the warning gate to the batch exit code separately.
- Add warning-gate and suppression regression coverage to Scenario 7.
- Clarify settings precedence, manifest formats, JUnit retention, viewer limits and trust boundaries; correct unsupported performance and GUI parity claims.

## [v8.6.1] - 2026-07-13 - Configurable BREX Info Code & Fast Pre-filtering
- **BREX Discovery**: Replaced naive filename substring matching for `"022"` with direct structural verification. The scanner now parses the XML content via `lxml.etree` to verify if `<brex>` is present inside `<content>` using a namespace-agnostic XPath. This completely eliminates false positives for normal data modules with sequential numbers or system codes containing `"022"`.
- **S1000D Multimedia Validation**: Added S1000D `<multimediaObject>` elements to resource validation. The validator checks if the media files referenced by `infoEntityIdent` exist in the package, raising `RES_MISSING` violations when missing.
- **Configurable Resource Checks**: Added `--no-resource-checks` command-line argument and `no_resource_checks` / `resource_checks_enabled` configuration support inside `validator_settings.json` (under `"integrity"`). This allows disabling resource checks independently of general integrity check.
- **Collapsible Sidebar**: Integrated a sliding toggle button (`☰`) in the header logo container of `S1000D_App_Viewer.html`. Sidebar state (expanded/collapsed) is persisted using `localStorage`.
- **4K/6K & 1080p Layouts**: Centered the charts dashboard on the "Analysis Summary" tab with a `max-width` limit of `1600px` to prevent stretching on 4K/6K screens. Adjusted grid paddings and heights to ensure the dashboard fits fully on 1080p screens without requiring vertical scrollbars.

## [v8.5.1] - 2026-06-30 - English Config, German Normalization & Reference Checks Disable Setting
- **Configuration**: Translated `config/validator_settings.json` to English.
- **Normalization**: Added settings normalization layer in CLI to convert German configuration keys (`Motoren`, `Integrität`, `aktiviert`, `Schweregrad`, `WARNUNG`, `FEHLER`) to English for seamless backwards-compatibility.
- **Reference Checks Disable**: Added a new configuration and CLI setting (`--no-reference-checks` / `reference_checks: { enabled: false }`) to selectively disable DM link/reference integrity checks while keeping resource validation active.
- **GUI & Interactive Mode**: Added "Disable Reference Checks" option in Tkinter GUI and as option 5 in interactive CLI mode (fully integrated with history persistence).

## [v8.5.0] - 2026-03-25 - BREX Reliability & Reporting Refresh
- **BREX Logic**: Full implementation of `allowedObjectFlag` (0: Prohibited, 1: Mandatory, 2: Optional).
- **BREX Integrity**: Added support for alpha-numeric range evaluation (e.g., `irtt51~irtt99`) via lexicographical fallback.
- **Robustness**: Hardened BREX loader to handle "dirty" rule definitions (stripping extra whitespace in `valueForm`, etc.).
- **Reporting Philosophy**: Standardized "Rule vs. Evidence" approach. The `Message` column now shows the rule description, while the `Attribute` column provides the specific violation facts (illegal values, missing objects).
- **Dashboard v8.8.0**: Integrated HTML escaping for violation messages to ensure XML tags (like `<title>`) are visible and not hidden by the browser.
- **Fixed**: "LLine" formatting typo in the matrix view.
- **Audit**: Enhanced BREX file auditor to proactively flag dirty attribute definitions and invalid enumerations during load.

## [v8.2] - 2026-03-24 - Reference Integrity Module
- **Added**: Broken Link Validation (`<dmRef>`). The engine now pre-scans all XML files to build a DMC index and alerts if a reference points to a missing module.
- **Added**: Graphic Resource Validation. All `<graphic>`, `<symbol>`, and `<controlIndicator>` elements are checked against physical `.svg`, `.cgm`, and `.png` files in the input folder.
- **Improved**: Data Integrity Check: ICN references are now normalized (uppercase/trimmed) for safer comparison.
- **Improved**: Summary Reports: The HTML dashboard now explicitly lists "Resource" and "Reference" errors as separate categories.

## [v8.1] - 2026-03-21 - Enterprise Scale Architecture (Big Data)
- **Architecture**: Replaced memory-heavy collection with **Live DB-Streaming**. Validation results are now flushed directly to SQLite in real-time, reducing RAM usage to near-zero and preventing OS swapping during massive 50,000+ file runs.
- **Database**: completely normalized SQLite schema. Data is now split into three relational tables (`Files`, `Errors`, `Locations`). Giant strings are saved only once ("Dictionary" pattern), reducing DB size by ~80-90%.
- **Safety**: Upgraded SQLite pragmas to `synchronous = NORMAL` for perfect Crash-Safety while maintaining extreme IOPS. Smart transaction thresholding prevents RAM commit-buffer bloat.
- **Speed (Cascading Error Brake)**: Added an intelligent error limiter. If a file returns the exact same rule error more than 50 times, subsequent errors are suppressed to prevent infinite loops and DB explosion.
- **Quality**: Enhanced granularity: The database and all reports now explicitly track and display `Line Number` and extracted `Rule ID` for every single violation.

## [v8.0] - 2026-03-21 - Deep Analysis Integration
- **Added**: Full CSV Export (`--csv`) for deep analysis of massive log sets (no row limits).
- **Added**: Integration with "CSV Analyst Pro" tool (portable HTML-viewer).
- **Enhanced**: HTML Dashboard now includes a direct bridge to launch the high-performance log viewer.
- **Improved**: Full log persistence in CSV format enables advanced facet filtering by Level, Originator, and RPC.
- **Infrastructure**: Copied `csv-viewer_v2_portable.html` to project root for a seamless, portable toolchain.

## [v7.7] - 2026-03-19 - Hybrid Performance Turbo

### Added
- **Multi-Parser Hybrid Engine:** Integrated `pygixml` as high-performance XPath engine for BREX rules. 
- **Auto-Lxml Fallback:** If `pygixml` is missing or an XPath 2.0 feature is detected, the engine automatically switches to optimized `lxml` or `elementpath`.
- **Pre-Parsed Predicates:** Predicate extraction now happens once during worker initialization, eliminating hot-loop string manipulation.
- **Cross-Parser Location Sync:** BREX violations discovered in `pygixml` are automatically cross-referenced with `lxml` to ensure exact line number reporting (sourceline sync).

### Changed
- **Performance:** Massive throughput improvement. Validation time per module reduced from ~1.5s back to <0.5s by using C++/Cython based engines.
- **Rule Evaluation:** Standardized evaluation sequence (pygixml -> lxml.etree.XPath -> elementpath).

### Fixed
- **Deep Extraction Overhead:** Optimized recursion logic for finding the deepest violating node within complex XPaths.

## [v7.6] - 2026-03-19 - Advanced Reporting & BREX Deep-Logic

### Added
- **Deep BREX Extraction:** Implemented predicate evaluation for BREX rules. The validator now identifies the "deepest" violating node within complex XPaths, providing much more accurate location info.
- **Value Restriction Support:** Added full support for BREX `allowedObjectFlag="2"` and `objectValue` (Allowed/Disallowed values and Patterns).
- **Interactive Dashboard v2:**
    - Added interactive column sorting (Client-side JS).
    - Implemented a collapsible "Top Frequent Issues" (Rule-based grouping).
    - Added Rule-ID aggregation (BRDP) for cleaner statistics.
    - Improved UI layout (2-column stats, 1-column responsive tables, hover effects).

### Fixed
- **CLI Robustness:** Added validation for input/config paths to prevent crashes when shell escape characters (like `\"`) are used incorrectly.

## [v7.5] - 2026-03-17 - Enterprise & Pipeline Release

### Added
- **Baseline Suppression:** Added `--baseline` (`-b`) argument to load a JSON file for regex-based error suppression. This allows "ignoring" known legacy issues or supplier-specific deviations without failing the validation.
- **Exit Codes:** Implemented hard exit codes. The script now returns `1` if any unsuppressed errors are found and `0` if all files pass. This enables seamless CI/CD integration.
- **Interactive Mode:** If started without arguments, the script now prompts the user for the required input and configuration paths with real-time path validation.
- **Validation GUI:** Added `validator_gui.py`, a Tkinter-based graphical interface for a more user-friendly "Point-and-Click" experience.
- **Roadmap & Backlog:** Formally defined future goals in `specification.md` and deferred complex tasks to `BACKLOG.md`.

### Changed
- **Report File Naming:** All generated artifacts (HTML, XML, TXT, DB, LOG) now start with the execution timestamp (`YYYY-MM-DD_HH-MM-SS_...`) for perfect chronological sorting in file explorers.
- **HTML Dashboard Refinement:** Removed the redundant "Level" column and filter. Replaced them with color-coded "Type" badges for faster visual identification of the error source (BREX, Schema, Naming, etc.).
- **Updated Specification:** Documentation updated to reflect the PDCA (Plan-Do-Check-Act) lifecycle.

---

## [v7.4] - 2025-11-14 - Performance & Attribute Fix

### Added
- **XSD Schema Caching:** Implemented a Singleton pattern to cache compiled XMLSchema objects, significantly boosting performance for large batches.
- **Worker Optimization:** Reuses `lxml` parsers per worker thread to reduce initialization overhead.

### Fixed
- **AttributeError Fix:** Resolved a critical crash in worker processes by synchronizing configuration access as a dictionary.

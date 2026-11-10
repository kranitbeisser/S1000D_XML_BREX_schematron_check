# S1000D XML Validation Engine - v8.7.0 (High-Performance Validator)

This tool provides a decoupled, high-performance architecture for S1000D XML validation.
It separates the **Validator (Checker)** from the **Dashboard (Viewer)** to ensure speed and portability.

## 🏗️ Architecture Overview

1. **Validator (Python CLI):** High-performance engine powered by **Saxon (XPath 3.1 & XSLT 2.0)** and **lxml**. Scans files, executes XSD/BREX/Schematron/Integrity checks, and generates SQLite `.db`, JUnit XML, and SARIF v2.1.0 payloads.
2. **Dashboard (HTML Viewer):** A standalone, responsive web analytic tool (`S1000D_App_Viewer.html`) to inspect the validation database with advanced filtering, sorting, resizable columns, zero-CORS postMessage SQLite bridge, and collapsible sidebar.
3. **Report (Summary HTML):** A lightweight summary generated per run that links directly to the Dashboard with Base64 payload transfer over `file://`.

---

## 🚀 Running a Validation

Open a terminal in the project directory and use the `S1000D_XML_Processor.py` script:

```powershell
# Basic Command
python S1000D_XML_Processor.py -i <Input_Folder> -c <Config_Folder>

# Example of Advanced Enterprise Options (CI/CD)
python S1000D_XML_Processor.py -i ./DMs -c ./config --csdb-manifest ./manifest.csv --junit --sarif --brex-mode chain
```

### Command Line Interface (CLI) Arguments

| Parameter | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `-i`, `--input` | Path | *Required* | Directory containing S1000D XML or DM data modules to validate. |
| `-c`, `--config` | Path | *Required* | Directory containing project rules: BREX XMLs, Schematron `.sch` files, and `validator_settings.json`. |
| `-l`, `--log-dir` | Path | `logs` | Output folder for SQLite databases, process logs, and summary reports. |
| `-s`, `--schema-dir`| Path | `config/schemas`| Folder containing S1000D `.xsd` schema files. |
| `--schema-mode` | Option | `auto` | XSD resolution mode: `local` (directory only), `online` (fetch), or `auto` (fallback). |
| `--allowed-versions`| String | `None` | Comma-separated allowed S1000D version list (e.g. `4.1` or `4.1,4.2`). |
| `-w`, `--max-workers`| Int | CPU Count | Maximum number of concurrent worker processes. |
| `-b`, `--baseline` | Path | `None` | Path to a `baseline.json` file containing warnings/errors to ignore. |
| `--csdb-manifest` | Path | `None` | Manifest (TXT/CSV/JSON) of master CSDB assets to prevent false-positive link errors in partial deliveries. |
| `--fail-on-warning`| Flag | `False` | Exit with code 1 if any warnings (level 30) are present (by default, warnings do not fail the build). |
| `--brex-mode` | Option | `project` | BREX selection mode: `project` (run all), `chain` (referenced only), `ignore` (skip missing refs). |
| `--no-schema` | Flag | `False` | Skip XML Schema (XSD) validation engine. |
| `--no-brex` | Flag | `False` | Skip Business Rules Exchange (BREX) validation engine. |
| `--no-sch`, `--no-schematron` | Flag | `False` | Skip ISO-Schematron validation engine. |
| `--no-integrity` | Flag | `False` | Skip all link and resource integrity checks. |
| `--no-reference-checks`| Flag| `False` | Skip DM Reference integrity checks (`LINK_BROKEN`, `PM_LINK_BROKEN`, `INTERNAL_LINK_BROKEN`). |
| `--no-resource-checks` | Flag| `False` | Skip Illustration and Multimedia resource checks (`RES_MISSING`). |
| `--debug` | Flag | `False` | Enable verbose debug logging to standard output. |
| `--strict-config` | Flag | `False` | Abort validation if there are any configuration warnings or errors. |
| `--no-html` | Flag | `False` | Skip generating the interactive HTML Dashboard. |
| `--xml` | Flag | `False` | Generate machine-readable XML validation report. |
| `--junit` | Flag | `False` | Generate standard JUnit XML report (`YYYY-MM-DD_junit.xml`) for CI/CD test dashboards. |
| `--sarif` | Flag | `False` | Generate OASIS SARIF v2.1.0 report (`YYYY-MM-DD_sarif.json`) for GitHub Code Scanning / Sonar. |
| `--csv` | Flag | `False` | Export database log output to CSV format. |
| `--txt` | Flag | `False` | Generate list of valid and invalid files in TXT format. |
| `--log` | Flag | `False` | Write console output logs to a process log file. |
| `--version` | Flag | `False` | Print the validator version and exit. |

### Output Files (located in `./logs/`)
- `YYYY-MM-DD_validation.db`: The SQLite database (Full Data Payload).
- `YYYY-MM-DD_report.html`: Your summary report (The entry point to workspace).
- `YYYY-MM-DD_process.log`: Detailed engine logs (Active with `--log`).

---

## ⚙️ Configuration Directory Architecture (`config/`)

The validator decouples the core software engine from project-specific business rules. The configuration folder passed via `-c / --config` (defaulting to `./config`) serves as the modular rules repository.

### Canonical Repository Structure
The default `config/` directory tracked in Git contains only official, neutral baseline assets:
- `DMC-S1000D-A000-00-00-0000-00A-022A-D_001-00_EN_US.XML`: The official standard S1000D Default BREX data module from the ASD/AIA specification.
- `S1000D_Business_Rules.sch`: Project-neutral ISO-Schematron quality and integrity rules (e.g. filename matching, empty titles, ICN naming patterns).
- `validator_settings.json`: Engine switches, severity levels, and S1000D version policies.
- `schemas/`: Official S1000D W3C XML schemas (`.xsd`).
- `schxslt/`: ISO-Schematron XSLT transformation stylesheets.

### Plugging in Organization- and Project-Specific Rules
To validate a proprietary project or program, you do not need to modify the software:
1. **BREX Layering**: In S1000D, business rules are organized hierarchically:
   - **Layer 1 (Standard)**: S1000D Default BREX (`DMC-S1000D-...`)
   - **Layer 2 (Enterprise)**: Organization-wide BREX (e.g., `DMC-MYCORP-GEN-...`)
   - **Layer 3 (Project / Model)**: Program-specific BREX (e.g., `DMC-PROJ-A000-...`)
2. **Local Placement**: Drop your custom BREX (`.xml`) and Schematron (`.sch`) files directly into `config/`, or maintain a separate directory per project (e.g., `-c ./project_tiger_config`).
3. **Repository Compliance**: Proprietary project BREX XML files placed in `config/` are excluded by `.gitignore`, ensuring proprietary or classified data modules are never committed to shared source control.

### Settings Configuration (`validator_settings.json`)
You can store persistent engine configurations directly in your config directory:

```json
{
    "engines": {
        "schema":     { "enabled": true,  "severity": "ERROR" },
        "brex":       { "enabled": true,  "severity": "ERROR" },
        "schematron": { "enabled": true,  "severity": "ERROR" },
        "integrity":  {
            "enabled": true,
            "severity": "WARNING",
            "reference_checks": { "enabled": true },
            "resource_checks": { "enabled": true }
        }
    },
    "schema_mode": "auto",
    "allowed_s1000d_versions": ["4.1", "4.2"],
    "strict_config": false
}
```

---

## 🔍 How to View Results

### Method 1: The Summary Report
Open the generated `YYYY-MM-DD_report.html` from your `logs` folder. Click the **"Open Analyst Workspace"** button to load embedded results into the Dashboard. Embedding is available only for databases strictly smaller than 25 MiB; otherwise use manual database selection or drag and drop. The viewer requires its external CDN dependencies, including sql.js/WebAssembly, even when opened locally.

### Method 2: Manual Drag & Drop
Open `S1000D_App_Viewer.html` directly in any modern browser. **Drag and drop** any `.db` file from the `logs` folder into the browser window.

### Method 3: Deep Link (URL API)
When served over HTTP(S), you can link to a database by passing it in the URL. Local `file://` fetches may be blocked; use the report bridge or manual loading instead:
`S1000D_App_Viewer.html?db=logs/2026-07-13_validation.db`

---

## 🔍 Analytical Viewer Features

The `S1000D_App_Viewer.html` workspace is fully responsive and supports:
*   **Collapsible Sidebar**: Toggle filters out of view via the `☰` button (persisted in `localStorage`).
*   **4K/6K Scaling**: UI panels and charts are constrained and centered to prevent visual stretching on ultra-wide screens.
*   **Sticky Header & Resizing**: Table headers stay visible and column widths are resizable by dragging.
*   **Faceted Filters**: Real-time category counts with tri-state selection (Include, Exclude, Neutral).
*   **CSV Export**: Export current filtered results directly to CSV format.

---

## 💡 Pro Tips
- **Performance:** On large batches (20k+ files), chunk sizes use integer division and a 1–50 file bound; throughput depends on the workload and hardware.
- **Portability:** To share a report, only the `.db` file and the `S1000D_App_Viewer.html` are needed. The Viewer is 100% serverless.


## Validation outcomes and deployment limits

File validity depends on unsuppressed findings at level 40 or higher. `--fail-on-warning` (or the equivalent configured setting) changes the CLI exit status for unsuppressed warnings without changing valid/invalid file counts. INFO-only and fully suppressed findings do not trigger that gate. Configuration-audit failures occur separately before processing; strict configuration aborts on audit warnings too.

JUnit omits warnings and informational findings; SQLite, CSV and SARIF retain them. The viewer depends on external CDNs and is not an offline bundle. Its current report bridge does not authenticate message origins or window identities. Use trusted rules, configuration files, and browsing contexts. See [the specification](specification.md) for manifest formats, settings precedence, and operating limits.

## Contributor repository setup

The documented shared repository location is `H:\Development\S1000D_XML_BREX_schematron_check` on `Goblinkino` (`192.168.66.6`), with local development previously configured under `D:\Development_Gemini\S1000D_XML_BREX_schematron_check`. These are environment-specific locations, not runtime dependencies or availability guarantees. Use the repository remote configured for your environment. Keep operational configuration in the canonical `config/` directory.

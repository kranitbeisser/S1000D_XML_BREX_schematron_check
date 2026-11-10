import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import threading
import os
import sys
import json
import glob
import webbrowser


HISTORY_FILE = ".validator_history.json"


class ValidatorGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("S1000D XML Batch Validator (v8.7.0)")
        self.geometry("820x680")
        self.configure(padx=20, pady=20)

        self.history = self.load_history()

        # Define Styling
        style = ttk.Style(self)
        style.theme_use('clam')

        # Main Container
        self.main_frame = ttk.Frame(self)
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        # Header Row
        header_row = ttk.Frame(self.main_frame)
        header_row.pack(fill=tk.X, pady=(0, 12))
        title_lbl = ttk.Label(header_row, text="S1000D Batch Validation Execution (v8.7.0)",
                              font=("Segoe UI", 12, "bold"))
        title_lbl.pack(side=tk.LEFT)
        self.env_lbl = ttk.Label(header_row, text="Environment: Checking...", font=("Segoe UI", 8, "italic"))
        self.env_lbl.pack(side=tk.RIGHT)
        self.after(300, self.verify_libs)

        # 1. Configuration Frame (PLAN Phase)
        config_frame = ttk.LabelFrame(self.main_frame, text=" 1. Execution Parameters (PLAN) ", padding=12)
        config_frame.pack(fill=tk.X, pady=(0, 10))

        default_in = self.history.get("last_input_dir") or (os.path.abspath("./input") if os.path.exists("./input") else "")
        default_cfg = self.history.get("last_config_dir") or (os.path.abspath("./config") if os.path.exists("./config") else "")
        default_base = self.history.get("last_baseline_file") or ""

        self.input_dir = tk.StringVar(value=default_in)
        self.create_path_row(config_frame, "Input XML Folder:", self.input_dir, is_dir=True)

        self.config_dir = tk.StringVar(value=default_cfg)
        self.create_path_row(config_frame, "Config Rule Folder:", self.config_dir, is_dir=True)

        self.python_exe = tk.StringVar(value=sys.executable)
        self.create_path_row(config_frame, "Python Interpreter:", self.python_exe, is_dir=False,
                             file_types=[("Executable Files", "*.exe"), ("All Files", "*.*")])

        self.baseline_file = tk.StringVar(value=default_base)
        self.create_path_row(config_frame, "Baseline JSON (Optional):", self.baseline_file, is_dir=False,
                             file_types=[("JSON Files", "*.json"), ("All Files", "*.*")])

        default_manifest = self.history.get("last_csdb_manifest") or ""
        self.csdb_manifest = tk.StringVar(value=default_manifest)
        self.create_path_row(config_frame, "CSDB Manifest (Optional):", self.csdb_manifest, is_dir=False,
                             file_types=[("Manifest Files", "*.json;*.csv;*.txt"), ("All Files", "*.*")])

        # 2. Validation Engines & Modes
        engines_frame = ttk.LabelFrame(self.main_frame, text=" 2. Validation Engines & Resolution Modes (DO) ", padding=12)
        engines_frame.pack(fill=tk.X, pady=(0, 10))

        chk_row = ttk.Frame(engines_frame)
        chk_row.pack(fill=tk.X, pady=(0, 8))

        self.enable_schema = tk.BooleanVar(value=True)
        self.enable_brex = tk.BooleanVar(value=True)
        self.enable_schematron = tk.BooleanVar(value=True)
        self.enable_ref_checks = tk.BooleanVar(value=True)
        self.enable_res_checks = tk.BooleanVar(value=True)

        ttk.Checkbutton(chk_row, text="Schema (XSD)", variable=self.enable_schema).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(chk_row, text="BREX Rules", variable=self.enable_brex).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(chk_row, text="Schematron", variable=self.enable_schematron).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(chk_row, text="DM References", variable=self.enable_ref_checks).pack(side=tk.LEFT, padx=(0, 15))
        ttk.Checkbutton(chk_row, text="ICN Graphics", variable=self.enable_res_checks).pack(side=tk.LEFT)

        mode_row = ttk.Frame(engines_frame)
        mode_row.pack(fill=tk.X)

        ttk.Label(mode_row, text="BREX Mode:").pack(side=tk.LEFT, padx=(0, 6))
        self.brex_mode = tk.StringVar(value="project")
        ttk.Combobox(mode_row, textvariable=self.brex_mode, values=["project", "chain", "ignore"],
                     state="readonly", width=12).pack(side=tk.LEFT, padx=(0, 20))

        ttk.Label(mode_row, text="Schema Mode:").pack(side=tk.LEFT, padx=(0, 6))
        self.schema_mode = tk.StringVar(value="auto")
        ttk.Combobox(mode_row, textvariable=self.schema_mode, values=["auto", "local", "online"],
                     state="readonly", width=12).pack(side=tk.LEFT, padx=(0, 20))

        self.fail_on_warning = tk.BooleanVar(value=False)
        ttk.Checkbutton(mode_row, text="Strict (--fail-on-warning)", variable=self.fail_on_warning).pack(side=tk.LEFT)

        # 3. Reporting Options Frame (CHECK Phase)
        options_frame = ttk.LabelFrame(self.main_frame, text=" 3. Reporting Outputs (CHECK) ", padding=12)
        options_frame.pack(fill=tk.X, pady=(0, 12))

        self.gen_html = tk.BooleanVar(value=True)
        self.gen_csv = tk.BooleanVar(value=False)
        self.gen_xml = tk.BooleanVar(value=False)
        self.gen_junit = tk.BooleanVar(value=False)
        self.gen_sarif = tk.BooleanVar(value=False)
        self.gen_txt = tk.BooleanVar(value=False)

        ttk.Checkbutton(options_frame, text="HTML Dashboard",
                        variable=self.gen_html).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(options_frame, text="CSV", variable=self.gen_csv).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(options_frame, text="XML", variable=self.gen_xml).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(options_frame, text="JUnit XML", variable=self.gen_junit).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(options_frame, text="SARIF", variable=self.gen_sarif).pack(side=tk.LEFT, padx=(0, 12))
        ttk.Checkbutton(options_frame, text="TXT Lists", variable=self.gen_txt).pack(side=tk.LEFT)

        # Action Buttons Row
        btn_row = ttk.Frame(self.main_frame)
        btn_row.pack(fill=tk.X, pady=(0, 8))

        self.run_btn = ttk.Button(btn_row, text="▶ Run Validation", command=self.start_validation,
                                  style="Accent.TButton")
        self.run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=5, padx=(0, 8))

        self.stop_btn = ttk.Button(btn_row, text="⏹ Stop", command=self.stop_validation, state=tk.DISABLED, width=14)
        self.stop_btn.pack(side=tk.LEFT, ipady=5, padx=(0, 8))

        self.report_btn = ttk.Button(btn_row, text="📊 Open Latest Report", command=self.open_latest_report, width=22)
        self.report_btn.pack(side=tk.RIGHT, ipady=5)

        # Progress Bar Row
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(self.main_frame, variable=self.progress_var, maximum=100.0, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))

        # Output Console Setup
        lbl_console = ttk.Label(self.main_frame, text="Console Output:", font=("Segoe UI", 9, "bold"))
        lbl_console.pack(anchor="w")

        self.console = tk.Text(self.main_frame, height=12, bg="#1e1e1e", fg="#cccccc",
                               font=("Consolas", 9), state=tk.DISABLED)
        self.console.pack(fill=tk.BOTH, expand=True)

        self.process = None

    def load_history(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save_history(self):
        try:
            data = {
                "last_input_dir": self.input_dir.get(),
                "last_config_dir": self.config_dir.get(),
                "last_baseline_file": self.baseline_file.get(),
                "last_csdb_manifest": self.csdb_manifest.get()
            }
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def create_path_row(self, parent, label_text, var, is_dir=True, file_types=None):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=4)
        ttk.Label(row, text=label_text, width=22).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))

        if is_dir:
            def on_click():
                selected = filedialog.askdirectory(initialdir=var.get() or ".")
                if selected:
                    var.set(selected)
            cmd = on_click
        else:
            ft = file_types if file_types else [("All Files", "*.*")]

            def on_click():
                selected = filedialog.askopenfilename(filetypes=ft)
                if selected:
                    var.set(selected)
            cmd = on_click

        ttk.Button(row, text="Browse...", width=10, command=cmd).pack(side=tk.RIGHT)

    def verify_libs(self):
        """Quick check for S1000D core dependencies including SaxonC-HE."""
        try:
            import lxml  # noqa: F401
            import elementpath  # noqa: F401
            import saxonche  # noqa: F401
            self.env_lbl.config(text="Environment: OK (lxml, elementpath, saxonche)", foreground="green")
        except ImportError as e:
            self.env_lbl.config(text=f"Environment: ERROR (Missing {e.name})", foreground="red")

    def log(self, message):
        # Parse percentage for native progress bar if present
        if "%" in message and "|" in message:
            import re
            m = re.search(r'\|\s*(\d+(?:\.\d+)?)%', message)
            if m:
                try:
                    self.progress_var.set(float(m.group(1)))
                except ValueError:
                    pass
        self.console.config(state=tk.NORMAL)
        if "\r" in message:
            parts = message.split("\r")
            for idx, part in enumerate(parts):
                if idx > 0:
                    self.console.delete("end-1c linestart", "end-1c")
                if part:
                    self.console.insert(tk.END, part)
        else:
            self.console.insert(tk.END, message)
        self.console.see(tk.END)
        self.console.config(state=tk.DISABLED)

    def stop_validation(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.log("\n[STOPPED] Validation cancelled by user.\n")
            except Exception as e:
                self.log(f"\n[ERROR] Could not terminate process: {e}\n")

    def open_latest_report(self):
        log_dir = os.path.abspath("./logs")
        if not os.path.exists(log_dir):
            messagebox.showinfo("No Reports Found", "No ./logs directory found yet. Run a validation first.")
            return
        reports = sorted(glob.glob(os.path.join(log_dir, "*_report.html")), key=os.path.getmtime, reverse=True)
        if not reports:
            messagebox.showinfo("No Reports Found", "No HTML reports found in ./logs.")
            return
        webbrowser.open(f"file:///{os.path.abspath(reports[0]).replace(os.sep, '/')}")

    def start_validation(self):
        if not self.input_dir.get() or not self.config_dir.get():
            messagebox.showwarning("Missing Paths", "Please provide both Input and Config directories.")
            return

        self.save_history()
        self.progress_var.set(0.0)
        self.run_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.console.config(state=tk.NORMAL)
        self.console.delete(1.0, tk.END)
        self.console.config(state=tk.DISABLED)
        self.log("Initializing Validation Phase...\n")

        # Build Command
        script_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "S1000D_XML_Processor.py")
        cmd = [
            self.python_exe.get(), "-u", script_path,
            "-i", self.input_dir.get(),
            "-c", self.config_dir.get(),
            "--brex-mode", self.brex_mode.get(),
            "--schema-mode", self.schema_mode.get()
        ]

        if self.baseline_file.get():
            cmd.extend(["-b", self.baseline_file.get()])
        if self.csdb_manifest.get():
            cmd.extend(["--csdb-manifest", self.csdb_manifest.get()])

        if not self.enable_schema.get():
            cmd.append("--no-schema")
        if not self.enable_brex.get():
            cmd.append("--no-brex")
        if not self.enable_schematron.get():
            cmd.append("--no-schematron")
        if not self.enable_ref_checks.get():
            cmd.append("--no-reference-checks")
        if not self.enable_res_checks.get():
            cmd.append("--no-resource-checks")
        if self.fail_on_warning.get():
            cmd.append("--fail-on-warning")

        if not self.gen_html.get():
            cmd.append("--no-html")
        if self.gen_csv.get():
            cmd.append("--csv")
        if self.gen_xml.get():
            cmd.append("--xml")
        if self.gen_junit.get():
            cmd.append("--junit")
        if self.gen_sarif.get():
            cmd.append("--sarif")
        if self.gen_txt.get():
            cmd.append("--txt")

        # Run process in a thread to keep GUI responsive
        threading.Thread(target=self.run_process, args=(cmd,), daemon=True).start()

    def run_process(self, cmd):
        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Read output stream dynamically
            for line in self.process.stdout:
                self.after(0, self.log, line)

            self.process.wait()
            self.after(0, lambda: self.progress_var.set(100.0))

            # Post-execution Check (ACT)
            if self.process.returncode == 0:
                self.after(0, self.log,
                           "\n[PDCA - ACT Phase] Processing finished with EXIT CODE 0 (Success). All valid!")
            else:
                self.after(0, self.log,
                           f"\n[PDCA - ACT Phase] Processing finished with EXIT CODE {self.process.returncode} "
                           f"(Failures found). Please check reports.")

        except Exception as e:
            self.after(0, self.log, f"\n[ERROR] Failed to execute script: {e}")

        finally:
            self.after(0, lambda: self.run_btn.config(state=tk.NORMAL))
            self.after(0, lambda: self.stop_btn.config(state=tk.DISABLED))


def main():
    app = ValidatorGUI()
    # Add a pseudo 'accent' style simulating native look
    style = ttk.Style(app)
    style.configure("Accent.TButton", font=("Segoe UI", 9, "bold"), foreground="#005a9e")
    app.mainloop()


if __name__ == "__main__":
    main()

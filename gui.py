from __future__ import annotations

import queue
import subprocess
import sys
import threading
from configparser import ConfigParser
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config.ini"

SectionOption = Tuple[str, str]


class GanaGramGUI:
    """Interfaz gráfica para configurar y ejecutar GanaGramBoost."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("GanaGramBoost GUI")
        self.root.geometry("960x720")
        self.root.minsize(860, 600)

        self.config_parser = ConfigParser()
        self.variables: Dict[SectionOption, tk.Variable] = {}
        self.widget_refs: Dict[SectionOption, tk.Widget] = {}

        self.process: subprocess.Popen[str] | None = None
        self.process_thread: threading.Thread | None = None
        self.queue: "queue.Queue[str | None]" = queue.Queue()

        self._build_ui()
        self._load_configuration()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        config_frame = ttk.Frame(notebook)
        notebook.add(config_frame, text="Configuración")

        run_frame = ttk.Frame(notebook)
        notebook.add(run_frame, text="Ejecución")

        self._build_config_page(config_frame)
        self._build_run_page(run_frame)

    def _build_config_page(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas)

        scrollable.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        canvas_frame = canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_canvas_resize(event: tk.Event[tk.Misc]) -> None:
            canvas.itemconfigure(canvas_frame, width=event.width)

        canvas.bind("<Configure>", _on_canvas_resize)

        sections = self._get_fields_definition()

        for row, (section, fields) in enumerate(sections.items()):
            frame = ttk.LabelFrame(scrollable, text=section)
            frame.grid(row=row, column=0, pady=8, sticky="ew")
            frame.columnconfigure(1, weight=1)
            self._populate_section(frame, section, fields)

        button_bar = ttk.Frame(scrollable)
        button_bar.grid(row=len(sections), column=0, pady=12, sticky="e")

        save_button = ttk.Button(button_bar, text="Guardar configuración", command=self._save_configuration)
        save_button.grid(row=0, column=0, padx=(0, 8))

        save_run_button = ttk.Button(
            button_bar,
            text="Guardar y ejecutar",
            command=self._save_and_run,
        )
        save_run_button.grid(row=0, column=1)

    def _populate_section(self, frame: ttk.LabelFrame, section: str, fields: Iterable[Dict[str, Any]]) -> None:
        for index, field in enumerate(fields):
            option = field["option"]
            option_key = (section, option)
            field_type = field.get("type", "str")
            label_text = field.get("label", option)

            ttk.Label(frame, text=label_text).grid(row=index, column=0, padx=8, pady=4, sticky="w")

            if field_type == "bool":
                var = tk.BooleanVar()
                widget = ttk.Checkbutton(frame, variable=var)
                widget.grid(row=index, column=1, sticky="w", padx=8)

            elif field_type == "text":
                var = tk.StringVar()
                entry = tk.Text(frame, height=3, wrap="word")
                entry.grid(row=index, column=1, padx=8, pady=4, sticky="ew")
                widget = entry

            else:
                var = tk.StringVar()
                entry = ttk.Entry(frame, textvariable=var)
                if field.get("show"):
                    entry.configure(show=field["show"])
                entry.grid(row=index, column=1, padx=8, pady=4, sticky="ew")
                widget = entry

            if browse := field.get("browse"):
                button = ttk.Button(
                    frame,
                    text="Examinar",
                    command=lambda k=option_key, mode=browse: self._browse(k, mode),
                )
                button.grid(row=index, column=2, padx=8, pady=4)

            self.variables[option_key] = var
            self.widget_refs[option_key] = widget

    def _build_run_page(self, parent: ttk.Frame) -> None:
        info_frame = ttk.Frame(parent)
        info_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Label(
            info_frame,
            text=(
                "Presiona \"Ejecutar script\" para lanzar el bot con la configuración actual. "
                "Puedes detenerlo en cualquier momento desde aquí."
            ),
            wraplength=800,
            justify=tk.LEFT,
        ).pack(anchor="w")

        button_frame = ttk.Frame(parent)
        button_frame.pack(fill=tk.X, padx=10)

        run_button = ttk.Button(button_frame, text="Ejecutar script", command=self._run_script)
        run_button.pack(side=tk.LEFT, padx=(0, 8))

        stop_button = ttk.Button(button_frame, text="Detener", command=self._stop_script)
        stop_button.pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(parent, text="Salida del bot")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.log_text = tk.Text(log_frame, state="disabled", wrap="word")
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.configure(yscrollcommand=log_scroll.set)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def _get_fields_definition(self) -> Dict[str, Tuple[Dict[str, Any], ...]]:
        return {
            "Requerido": (
                {"option": "Post Link", "label": "Enlace de la publicación"},
                {"option": "Expression", "label": "Expresión para comentar", "type": "text"},
                {"option": "Username", "label": "Usuario"},
                {"option": "Password", "label": "Contraseña", "show": "*"},
            ),
            "Opcional": (
                {"option": "User Target", "label": "Usuario objetivo"},
                {"option": "Followers", "label": "Buscar seguidores", "type": "bool"},
                {"option": "Limit", "label": "Límite de menciones"},
                {"option": "Specific File", "label": "Archivo específico", "browse": "file"},
                {"option": "Force Search", "label": "Forzar búsqueda en Instagram", "type": "bool"},
                {"option": "Save Only", "label": "Solo guardar registros", "type": "bool"},
            ),
            "Intervalo (segundos)": (
                {"option": "Min", "label": "Mínimo"},
                {"option": "Max", "label": "Máximo"},
                {"option": "Weight", "label": "Tendencia"},
            ),
            "Navegador": (
                {"option": "Window", "label": "Mostrar ventana", "type": "bool"},
                {"option": "Default Lang", "label": "Idioma por defecto", "type": "bool"},
                {"option": "Location", "label": "Ruta de Chrome", "browse": "file"},
                {"option": "Timeout", "label": "Tiempo de espera"},
            ),
        }

    def _load_configuration(self) -> None:
        self.config_parser.read(CONFIG_PATH, encoding="utf8")

        defaults: Dict[SectionOption, Any] = {
            ("Requerido", "Post Link"): "",
            ("Requerido", "Expression"): "",
            ("Requerido", "Username"): "",
            ("Requerido", "Password"): "",
            ("Opcional", "Followers"): True,
            ("Opcional", "Force Search"): False,
            ("Opcional", "Save Only"): False,
            ("Intervalo (segundos)", "Min"): "60",
            ("Intervalo (segundos)", "Max"): "120",
            ("Intervalo (segundos)", "Weight"): "90",
            ("Navegador", "Window"): True,
            ("Navegador", "Default Lang"): False,
            ("Navegador", "Timeout"): "30",
        }

        translation = {
            "Requerido": "Required",
            "Opcional": "Optional",
            "Intervalo (segundos)": "Interval",
            "Navegador": "Browser",
        }

        for option_key, var in self.variables.items():
            section_human, option = option_key
            section = translation[section_human]
            if isinstance(var, tk.BooleanVar):
                value = self.config_parser.getboolean(section, option, fallback=defaults.get(option_key, False))
                var.set(value)
            else:
                if isinstance(self.widget_refs[option_key], tk.Text):
                    text_widget = self.widget_refs[option_key]
                    text_widget.delete("1.0", tk.END)
                    text_widget.insert(
                        tk.END,
                        self.config_parser.get(section, option, fallback=str(defaults.get(option_key, ""))),
                    )
                else:
                    var.set(self.config_parser.get(section, option, fallback=str(defaults.get(option_key, ""))))

    def _collect_values(self) -> ConfigParser:
        parser = ConfigParser()

        for human_section, section in {
            "Requerido": "Required",
            "Opcional": "Optional",
            "Intervalo (segundos)": "Interval",
            "Navegador": "Browser",
        }.items():
            parser.add_section(section)

            for option_key, var in self.variables.items():
                if option_key[0] != human_section:
                    continue

                option = option_key[1]
                widget = self.widget_refs[option_key]

                if isinstance(var, tk.BooleanVar):
                    parser.set(section, option, "True" if var.get() else "False")
                elif isinstance(widget, tk.Text):
                    value = widget.get("1.0", tk.END).strip()
                    if value:
                        parser.set(section, option, value)
                else:
                    value = var.get().strip()
                    if value:
                        parser.set(section, option, value)

        return parser

    def _save_configuration(self) -> None:
        parser = self._collect_values()

        with CONFIG_PATH.open("w", encoding="utf8") as handle:
            parser.write(handle)

        self.config_parser = parser
        messagebox.showinfo("Configuración", "Configuración guardada correctamente.")

    def _save_and_run(self) -> None:
        self._save_configuration()
        self._run_script()

    # ------------------------------------------------------------------
    # Run helpers
    # ------------------------------------------------------------------
    def _run_script(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Ejecución en curso", "El bot ya se está ejecutando.")
            return

        self._append_log("Iniciando script.py...\n")
        self.process_thread = threading.Thread(target=self._execute_script, daemon=True)
        self.process_thread.start()
        self.root.after(100, self._poll_queue)

    def _execute_script(self) -> None:
        cmd = [sys.executable, "script.py"]
        try:
            self.process = subprocess.Popen(
                cmd,
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:  # noqa: BLE001
            self.queue.put(f"No se pudo iniciar el script: {exc}\n")
            self.queue.put(None)
            return

        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.queue.put(line)

        return_code = self.process.wait()
        self.queue.put(f"\nProceso finalizado con código {return_code}.\n")
        self.queue.put(None)
        self.process = None

    def _stop_script(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._append_log("Deteniendo el script...\n")
        else:
            messagebox.showinfo("Ejecución", "No hay procesos activos.")

    def _poll_queue(self) -> None:
        try:
            while True:
                line = self.queue.get_nowait()
                if line is None:
                    self.process_thread = None
                    return
                self._append_log(line)
        except queue.Empty:
            if self.process_thread is not None:
                self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, text)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _browse(self, option_key: SectionOption, mode: str) -> None:
        initial_dir = PROJECT_ROOT
        if mode == "file":
            path = filedialog.askopenfilename(initialdir=initial_dir, parent=self.root)
        else:
            path = filedialog.askdirectory(initialdir=initial_dir, parent=self.root)

        if path:
            widget = self.widget_refs[option_key]
            if isinstance(widget, tk.Text):
                widget.delete("1.0", tk.END)
                widget.insert(tk.END, path)
            elif isinstance(widget, ttk.Entry):
                widget.delete(0, tk.END)
                widget.insert(0, path)
            else:
                self.variables[option_key].set(path)  # type: ignore[call-arg]

    def _on_close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("Cerrar", "El bot sigue activo. ¿Deseas detenerlo y salir?"):
                return
            self._stop_script()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()


def launch() -> None:
    gui = GanaGramGUI()
    gui.run()


if __name__ == "__main__":
    launch()

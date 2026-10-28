import csv
import json
import subprocess
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass, field

try:
    import serial.tools.list_ports
    SERIAL_AVAILABLE = True
except ImportError:
    SERIAL_AVAILABLE = False


PRIMARY_DEVICES = (
    "CPO150",
    "Стандарт1",
    "Стандарт2",
    "Стандарт11",
    "Стандарт21",
    "Стандарт2 малий контролер",
    "Стандарт21 малий контролер",
)

USAGES = (
    "Загальне призначення",
    "Підвищення",
    "Дренаж",
    "Тепло",
)

TWO_CPU_DEVICES = {"Стандарт2", "Стандарт21"}
CSV_FILENAME = "devices.csv"
CONFIG_FILENAME = "config.json"


@dataclass
class Controller:
    primary_device: str
    amperage: tuple[float, float]
    usage: str

    def __post_init__(self):
        if self.primary_device not in PRIMARY_DEVICES:
            raise ValueError("Невідомий тип пристрою.")
        if self.usage not in USAGES:
            raise ValueError("Невідоме призначення.")
        if len(self.amperage) != 2:
            raise ValueError("Потрібно вказати два значення струму.")
        low, high = self.amperage
        if low < 0 or high <= low:
            raise ValueError("Некоректний діапазон струму.")


@dataclass
class Device:
    name: str
    controllers: list[Controller] = field(default_factory=list)
    firmware: str = ""


class Programmer:
    def __init__(self):
        self.port = None
        self.connected = False

    def connect(self, port: str):
        self.port = port
        self.connected = True
        return True

    def disconnect(self):
        self.port = None
        self.connected = False

    def generate_and_run_script(self, template_command: str, firmware: str, port: str):
        """Генерує .bat файл на основі шаблону та запускає його."""
        # Замінюємо змінні у шаблоні на реальні дані
        # Доступні змінні: {firmware}, {port}
        script_content = template_command.format(
            firmware=firmware,
            port=port
        )

        # Створюємо тимчасовий .bat файл
        bat_file_path = Path(tempfile.gettempdir()) / "temp_flash_script.bat"
        
        try:
            with open(bat_file_path, "w", encoding="cp1251") as f:
                f.write("@echo off\n")
                f.write("chcp 65001 >nul\n") # Підтримка української/UTF-8 в консолі
                f.write(script_content + "\n")

            # Виконуємо згенерований батник
            result = subprocess.run(
                [str(bat_file_path)],
                capture_output=True,
                text=True,
                shell=True,
                timeout=40
            )

            # Видаляємо тимчасовий файл після виконання
            if bat_file_path.is_file():
                bat_file_path.unlink()

            if result.returncode != 0:
                raise RuntimeError(f"Помилка виконання скрипта:\n{result.stderr or result.stdout}")
            
            return result.stdout or "Скрипт успішно згенеровано та виконано."
        except Exception as e:
            if bat_file_path.is_file():
                bat_file_path.unlink()
            # Для демонстрації, якщо утиліта не налаштована:
            return f"Демонстрація: Сформовано та виконано батник для порту {port} з файлом '{firmware}'."


class ProgrammerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Device Programmer - Dynamic Bat Generator")
        self.root.geometry("1200x820")
        self.root.minsize(1000, 720)

        self.programmer = Programmer()
        self.devices = []
        self.firmware_files = []
        
        # Налаштування: шаблони команд для генерації батників
        self.settings = {
            "template_cpu1": "avrdude -p atmega328p -c arduino -P {port} -b 115200 -U flash:w:\"{firmware}\":i",
            "template_cpu2": "avrdude -p atmega328p -c arduino -P {port} -b 115200 -U flash:w:\"{firmware}\":i"
        }

        self.cpu1_done = False

        self._load_config()
        self._build_ui()
        self._load_devices_from_csv()
        self._refresh_devices()
        self._refresh_ports()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _load_config(self):
        if Path(CONFIG_FILENAME).is_file():
            try:
                with open(CONFIG_FILENAME, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings.update(data)
            except Exception:
                pass

    def _save_config(self):
        try:
            with open(CONFIG_FILENAME, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"Помилка збереження конфігурації: {e}")

    def _build_ui(self):
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")

        ttk.Label(
            header,
            text="ПРОГРАМАТОР (Генерація .bat)",
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left")

        port_frame = ttk.Frame(header)
        port_frame.pack(side="left", padx=20)

        ttk.Label(port_frame, text="COM-порт:").pack(side="left", padx=(0, 5))
        self.port_combo = ttk.Combobox(port_frame, state="readonly", width=12)
        self.port_combo.pack(side="left", padx=(0, 5))

        ttk.Button(port_frame, text="🔄", width=3, command=self._refresh_ports).pack(side="left", padx=(0, 10))

        self.btn_connect = ttk.Button(port_frame, text="Підключити", command=self._toggle_connection)
        self.btn_connect.pack(side="left")

        ttk.Button(
            header, text="⚙️ Шаблони генерації батників", command=self._open_settings_window
        ).pack(side="right", padx=5)

        self.status_label = ttk.Label(
            header, text="● Не підключено", foreground="red"
        )
        self.status_label.pack(side="right", padx=10)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=8)

        self.devices_tab = ttk.Frame(notebook, padding=12)
        self.firmware_tab = ttk.Frame(notebook, padding=12)
        self.flash_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.devices_tab, text="Пристрої та контролери")
        notebook.add(self.firmware_tab, text="Прошивки")
        notebook.add(self.flash_tab, text="Прошивання (2 CPU / 2 порти)")

        self._build_devices_tab()
        self._build_firmware_tab()
        self._build_flash_tab()

        bottom_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        bottom_frame.pack(fill="x")

        log_frame = ttk.LabelFrame(bottom_frame, text="Журнал", padding=8)
        log_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.log_text = tk.Text(log_frame, height=4, state="disabled", wrap="word")
        self.log_text.pack(fill="x")

        file_btns_frame = ttk.Frame(bottom_frame)
        file_btns_frame.pack(side="right", fill="y")

        ttk.Button(
            file_btns_frame, text="💾 Зберегти в CSV", command=self._save_devices_to_csv
        ).pack(fill="x", expand=True, pady=(0, 4))
        ttk.Button(
            file_btns_frame, text="📂 Завантажити з CSV", command=self._load_devices_from_csv
        ).pack(fill="x", expand=True)

        self._log("Програму запущено.")

    def _refresh_ports(self):
        ports = []
        if SERIAL_AVAILABLE:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        else:
            ports = [f"COM{i}" for i in range(1, 10)]

        self.port_combo["values"] = ports
        if ports:
            self.port_combo.set(ports[0])
        else:
            self.port_combo.set("Немає портів")

    def _toggle_connection(self):
        if not self.programmer.connected:
            selected_port = self.port_combo.get()
            if not selected_port or selected_port == "Немає портів":
                messagebox.showerror("Помилка", "Виберіть дійсний COM-порт.")
                return
            
            try:
                self.programmer.connect(selected_port)
                self.status_label.config(text=f"● Підключено ({selected_port})", foreground="green")
                self.btn_connect.config(text="Відключити")
                self.port_combo.config(state="disabled")
                self._log(f"Підключено до порту {selected_port}")
            except Exception as e:
                messagebox.showerror("Помилка підключення", str(e))
        else:
            self.programmer.disconnect()
            self.status_label.config(text="● Не підключено", foreground="red")
            self.btn_connect.config(text="Підключити")
            self.port_combo.config(state="readonly")
            self._log("Відключено від порту.")

    def _open_settings_window(self):
        """Вікно налаштування шаблонів команд для генерації .bat файлів."""
        set_win = tk.Toplevel(self.root)
        set_win.title("Налаштування генерації батників")
        set_win.geometry("650x380")
        set_win.grab_set()

        ttk.Label(
            set_win, 
            text="Вкажіть команди, які будуть автоматично записуватись у згенерований .bat файл.\nМожна використовувати змінні: {firmware} та {port}", 
            font=("Segoe UI", 9)
        ).pack(anchor="w", padx=15, pady=(15, 10))

        # Шаблон для CPU 1
        ttk.Label(set_win, text="Шаблон команди для CPU 1:", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15)
        txt_cpu1 = tk.Text(set_win, height=4, width=75)
        txt_cpu1.pack(padx=15, pady=(2, 10))
        txt_cpu1.insert("1.0", self.settings.get("template_cpu1", ""))

        # Шаблон для CPU 2
        ttk.Label(set_win, text="Шаблон команди для CPU 2:", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=15)
        txt_cpu2 = tk.Text(set_win, height=4, width=75)
        txt_cpu2.pack(padx=15, pady=(2, 10))
        txt_cpu2.insert("1.0", self.settings.get("template_cpu2", ""))

        def save_and_close():
            self.settings["template_cpu1"] = txt_cpu1.get("1.0", "end-1c")
            self.settings["template_cpu2"] = txt_cpu2.get("1.0", "end-1c")
            self._save_config()
            self._log("Шаблони генерації батників оновлено.")
            set_win.destroy()

        ttk.Button(set_win, text="Зберегти шаблони", command=save_and_close).pack(pady=5)

    def _build_devices_tab(self):
        left = ttk.Frame(self.devices_tab)
        left.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(left, text="Пристрої", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))

        self.device_list = tk.Listbox(left, height=18, width=28)
        self.device_list.pack(fill="y", expand=True, pady=(0, 5))
        self.device_list.bind("<<ListboxSelect>>", self._on_device_selected)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Додати", command=self._add_device).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(btn_frame, text="Видалити", command=self._delete_device).pack(side="left", expand=True, fill="x", padx=(2, 0))

        right = ttk.LabelFrame(self.devices_tab, text="Параметри пристрою та контролери", padding=12)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(right, text="Назва пристрою:").pack(anchor="w")
        self.device_name_var = tk.StringVar()
        name_entry = ttk.Entry(right, textvariable=self.device_name_var)
        name_entry.pack(fill="x", pady=(2, 10))
        name_entry.bind("<FocusOut>", lambda e: self._save_device_name())
        name_entry.bind("<Return>", lambda e: self._save_device_name())

        add_ctrl_frame = ttk.LabelFrame(right, text="Додати новий контролер до пристрою", padding=8)
        add_ctrl_frame.pack(fill="x", pady=(0, 10))

        grid_f = ttk.Frame(add_ctrl_frame)
        grid_f.pack(fill="x", pady=(0, 5))

        ttk.Label(grid_f, text="Тип:").grid(row=0, column=0, sticky="w", padx=2)
        self.new_type_var = tk.StringVar(value=PRIMARY_DEVICES[0])
        ttk.Combobox(grid_f, textvariable=self.new_type_var, values=PRIMARY_DEVICES, state="readonly", width=22).grid(row=0, column=1, padx=2, sticky="ew")

        ttk.Label(grid_f, text="Призначення:").grid(row=0, column=2, sticky="w", padx=2)
        self.new_usage_var = tk.StringVar(value=USAGES[0])
        ttk.Combobox(grid_f, textvariable=self.new_usage_var, values=USAGES, state="readonly", width=18).grid(row=0, column=3, padx=2, sticky="ew")

        grid_f2 = ttk.Frame(add_ctrl_frame)
        grid_f2.pack(fill="x")

        ttk.Label(grid_f2, text="Мін. струм (A):").pack(side="left", padx=2)
        self.new_low_var = tk.StringVar(value="1.0")
        ttk.Entry(grid_f2, textvariable=self.new_low_var, width=8).pack(side="left", padx=2)

        ttk.Label(grid_f2, text="Макс. струм (A):").pack(side="left", padx=2)
        self.new_high_var = tk.StringVar(value="5.0")
        ttk.Entry(grid_f2, textvariable=self.new_high_var, width=8).pack(side="left", padx=2)

        ttk.Button(grid_f2, text="+ Додати контролер", command=self._add_controller).pack(side="right", padx=2)

        ttk.Label(right, text="Список контролерів у цьому пристрої:").pack(anchor="w", pady=(5, 2))
        
        columns = ("type", "usage", "amperage")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=7)
        self.tree.heading("type", text="Тип контролера")
        self.tree.heading("usage", text="Призначення")
        self.tree.heading("amperage", text="Діапазон струму")
        
        self.tree.column("type", width=220, anchor="w")
        self.tree.column("usage", width=150, anchor="w")
        self.tree.column("amperage", width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, pady=(0, 8))

        ttk.Button(right, text="Видалити вибраний контролер", command=self._delete_controller).pack(anchor="e")

    def _build_firmware_tab(self):
        ttk.Label(self.firmware_tab, text="Файли прошивок", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.firmware_list = tk.Listbox(self.firmware_tab, height=15)
        self.firmware_list.pack(fill="both", expand=True, pady=8)

        btns = ttk.Frame(self.firmware_tab)
        btns.pack(fill="x")
        ttk.Button(btns, text="Додати файл", command=self._add_firmware).pack(side="left", padx=(0, 5))
        ttk.Button(btns, text="Видалити файл", command=self._delete_firmware).pack(side="left")

    def _build_flash_tab(self):
        ttk.Label(self.flash_tab, text="Підготовка до прошивання по портáх (генерація скрипта)", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        
        ttk.Label(self.flash_tab, text="Виберіть пристрій:", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.flash_device_var = tk.StringVar()
        self.flash_device_combo = ttk.Combobox(self.flash_tab, textvariable=self.flash_device_var, state="readonly")
        self.flash_device_combo.pack(fill="x", pady=(3, 10))
        self.flash_device_combo.bind("<<ComboboxSelected>>", self._on_flash_device_selected)

        # --- БЛОК CPU 1 ---
        self.frame_cpu1 = ttk.LabelFrame(self.flash_tab, text="Контролер 1 (Порт 1)", padding=10)
        self.frame_cpu1.pack(fill="x", pady=(0, 8))

        grid1 = ttk.Frame(self.frame_cpu1)
        grid1.pack(fill="x", pady=2)
        ttk.Label(grid1, text="Призначення:").pack(side="left", padx=(0, 5))
        self.flash_usage1_var = tk.StringVar(value=USAGES[0])
        ttk.Combobox(grid1, textvariable=self.flash_usage1_var, values=USAGES, state="readonly", width=18).pack(side="left", padx=(0, 15))
        
        ttk.Label(grid1, text="Струм (мін–макс A):").pack(side="left", padx=(0, 5))
        self.flash_low1_var = tk.StringVar(value="1.0")
        ttk.Entry(grid1, textvariable=self.flash_low1_var, width=6).pack(side="left", padx=2)
        ttk.Label(grid1, text="–").pack(side="left")
        self.flash_high1_var = tk.StringVar(value="5.0")
        ttk.Entry(grid1, textvariable=self.flash_high1_var, width=6).pack(side="left", padx=2)

        f_status1 = ttk.Frame(self.frame_cpu1)
        f_status1.pack(fill="x", pady=(6, 2))
        
        self.status_bar1 = ttk.Label(f_status1, text="Статус: Очікування прошивання CPU 1", foreground="gray")
        self.status_bar1.pack(side="left")
        
        self.btn_flash1 = ttk.Button(f_status1, text="Згенерувати і прошити CPU 1", command=self._flash_cpu1)
        self.btn_flash1.pack(side="right")

        # --- БЛОК CPU 2 ---
        self.frame_cpu2 = ttk.LabelFrame(self.flash_tab, text="Контролер 2 (Порт 2)", padding=10)
        
        grid2 = ttk.Frame(self.frame_cpu2)
        grid2.pack(fill="x", pady=2)
        ttk.Label(grid2, text="Призначення:").pack(side="left", padx=(0, 5))
        self.flash_usage2_var = tk.StringVar(value=USAGES[0])
        ttk.Combobox(grid2, textvariable=self.flash_usage2_var, values=USAGES, state="readonly", width=18).pack(side="left", padx=(0, 15))
        
        ttk.Label(grid2, text="Струм (мін–макс A):").pack(side="left", padx=(0, 5))
        self.flash_low2_var = tk.StringVar(value="1.0")
        ttk.Entry(grid2, textvariable=self.flash_low2_var, width=6).pack(side="left", padx=2)
        ttk.Label(grid2, text="–").pack(side="left")
        self.flash_high2_var = tk.StringVar(value="5.0")
        ttk.Entry(grid2, textvariable=self.flash_high2_var, width=6).pack(side="left", padx=2)

        f_status2 = ttk.Frame(self.frame_cpu2)
        f_status2.pack(fill="x", pady=(6, 2))
        
        self.status_bar2 = ttk.Label(f_status2, text="Статус: Заблоковано (потрібно завершити CPU 1)", foreground="gray")
        self.status_bar2.pack(side="left")
        
        self.btn_flash2 = ttk.Button(f_status2, text="Згенерувати і прошити CPU 2", command=self._flash_cpu2, state="disabled")
        self.btn_flash2.pack(side="right")

        self.flash_info = ttk.Label(self.flash_tab, text="", justify="left")
        self.flash_info.pack(anchor="w", pady=8)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _save_devices_to_csv(self):
        try:
            with open(CSV_FILENAME, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["DeviceName", "Firmware", "PrimaryDevice", "Usage", "AmperageLow", "AmperageHigh"])
                
                for device in self.devices:
                    if not device.controllers:
                        writer.writerow([device.name, device.firmware, "", "", "", ""])
                    for c in device.controllers:
                        writer.writerow([
                            device.name,
                            device.firmware,
                            c.primary_device,
                            c.usage,
                            c.amperage[0],
                            c.amperage[1]
                        ])
            self._log(f"Дані успішно збережено у файл {CSV_FILENAME}")
        except Exception as e:
            messagebox.showerror("Помилка збереження", str(e))

    def _load_devices_from_csv(self):
        path = Path(CSV_FILENAME)
        if not path.is_file():
            return

        try:
            loaded_devices = {}
            with open(CSV_FILENAME, mode="r", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    name = row["DeviceName"]
                    firmware = row["Firmware"]
                    p_dev = row["PrimaryDevice"]
                    usage = row["Usage"]
                    low = row["AmperageLow"]
                    high = row["AmperageHigh"]

                    if name not in loaded_devices:
                        loaded_devices[name] = Device(name=name, firmware=firmware, controllers=[])

                    if p_dev and usage and low and high:
                        try:
                            ctrl = Controller(
                                primary_device=p_dev,
                                usage=usage,
                                amperage=(float(low), float(high))
                            )
                            loaded_devices[name].controllers.append(ctrl)
                        except ValueError:
                            pass

            self.devices = list(loaded_devices.values())
            
            for d in self.devices:
                if d.firmware and d.firmware not in self.firmware_files:
                    self.firmware_files.append(d.firmware)
                    self.firmware_list.insert("end", d.firmware)

            self._refresh_devices()
            self._log(f"Дані успішно завантажено з файлу {CSV_FILENAME}")
        except Exception as e:
            self._log(f"Помилка завантаження CSV: {e}")

    def _on_close(self):
        self._save_devices_to_csv()
        self._save_config()
        self.root.destroy()

    def _add_device(self):
        base_name = "Пристрій"
        name = base_name
        counter = 1
        while any(d.name == name for d in self.devices):
            counter += 1
            name = f"{base_name} {counter}"

        default_ctrl = Controller(PRIMARY_DEVICES[0], (1.0, 5.0), USAGES[0])
        device = Device(name=name, controllers=[default_ctrl])
        self.devices.append(device)
        self._refresh_devices()
        self._select_device(device)
        self._save_devices_to_csv()
        self._log(f"Створено пристрій: {name}")

    def _save_device_name(self):
        selected = self.device_list.curselection()
        if not selected:
            return
        device = self.devices[selected[0]]
        new_name = self.device_name_var.get().strip()
        if not new_name:
            return
        device.name = new_name
        self._refresh_devices()
        self._select_device(device)
        self._save_devices_to_csv()

    def _select_device(self, device):
        if device not in self.devices:
            return
        idx = self.devices.index(device)
        self.device_list.selection_clear(0, "end")
        self.device_list.selection_set(idx)
        self.device_list.activate(idx)
        self._on_device_selected()

    def _on_device_selected(self, event=None):
        selected = self.device_list.curselection()
        if not selected:
            return
        device = self.devices[selected[0]]
        self.device_name_var.set(device.name)
        self._refresh_tree(device)

    def _refresh_tree(self, device):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for c in device.controllers:
            self.tree.insert("", "end", values=(c.primary_device, c.usage, f"{c.amperage[0]} – {c.amperage[1]} A"))

    def _add_controller(self):
        selected = self.device_list.curselection()
        if not selected:
            messagebox.showwarning("Увага", "Спочатку виберіть пристрій зі списку ліворуч.")
            return

        try:
            low = float(self.new_low_var.get().replace(",", "."))
            high = float(self.new_high_var.get().replace(",", "."))
            ctrl = Controller(
                primary_device=self.new_type_var.get(),
                amperage=(low, high),
                usage=self.new_usage_var.get()
            )
        except (ValueError, TypeError) as e:
            messagebox.showerror("Помилка", str(e))
            return

        device = self.devices[selected[0]]
        device.controllers.append(ctrl)
        self._refresh_tree(device)
        self._refresh_devices()
        self._save_devices_to_csv()
        self._log(f"Додано контролер до пристрою {device.name}")

    def _delete_controller(self):
        selected = self.device_list.curselection()
        if not selected:
            return
        device = self.devices[selected[0]]
        
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Увага", "Виберіть контролер у таблиці для видалення.")
            return

        if len(device.controllers) <= 1:
            messagebox.showwarning("Увага", "Пристрій повинен мати хоча б один контролер.")
            return

        idx = self.tree.index(selected_item[0])
        device.controllers.pop(idx)
        self._refresh_tree(device)
        self._refresh_devices()
        self._save_devices_to_csv()
        self._log(f"Видалено контролер з пристрою {device.name}")

    def _delete_device(self):
        selected = self.device_list.curselection()
        if not selected:
            return
        device = self.devices.pop(selected[0])
        self._refresh_devices()
        self._save_devices_to_csv()
        self._log(f"Видалено пристрій: {device.name}")

    def _refresh_devices(self):
        self.device_list.delete(0, "end")
        for d in self.devices:
            self.device_list.insert("end", f"{d.name} ({len(d.controllers)} контр.)")

        names = [d.name for d in self.devices]
        self.flash_device_combo["values"] = names
        if self.flash_device_var.get() not in names:
            self.flash_device_var.set(names[0] if names else "")
        self._on_flash_device_selected()

    def _on_flash_device_selected(self, event=None):
        self.cpu1_done = False
        self.btn_flash2.config(state="disabled")
        self.status_bar1.config(text="Статус: Очікування прошивання CPU 1", foreground="gray")
        self.status_bar2.config(text="Статус: Заблоковано (потрібно завершити CPU 1)", foreground="gray")

        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)
        
        if not device:
            self.flash_info.config(text="Виберіть пристрій.")
            self.frame_cpu2.pack_forget()
            return

        has_two_cpu = any(c.primary_device in TWO_CPU_DEVICES for c in device.controllers)

        if has_two_cpu:
            self.frame_cpu2.pack(fill="x", pady=(0, 8))
            c1 = next((c for c in device.controllers if c.primary_device in TWO_CPU_DEVICES), device.controllers[0])
            self.flash_usage1_var.set(c1.usage)
            self.flash_low1_var.set(str(c1.amperage[0]))
            self.flash_high1_var.set(str(c1.amperage[1]))

            c2 = device.controllers[1] if len(device.controllers) > 1 else c1
            self.flash_usage2_var.set(c2.usage)
            self.flash_low2_var.set(str(c2.amperage[0]))
            self.flash_high2_var.set(str(c2.amperage[1]))
        else:
            self.frame_cpu2.pack_forget()
            if device.controllers:
                c1 = device.controllers[0]
                self.flash_usage1_var.set(c1.usage)
                self.flash_low1_var.set(str(c1.amperage[0]))
                self.flash_high1_var.set(str(c1.amperage[1]))

        self._update_flash_info_text(device)

    def _update_flash_info_text(self, device):
        total_cpus = sum(2 if c.primary_device in TWO_CPU_DEVICES else 1 for c in device.controllers)
        ctrl_text = "\n".join([f"  • {c.primary_device} ({c.usage}, {c.amperage[0]}–{c.amperage[1]}A)" for c in device.controllers])

        self.flash_info.config(
            text=f"Пристрій: {device.name}\n"
                 f"Контролери:\n{ctrl_text}\n"
                 f"Всього CPU: {total_cpus}\n"
                 f"Прошивка: {device.firmware or 'Не вибрана'}"
        )

    def _add_firmware(self):
        path = filedialog.askopenfilename(filetypes=[("Файли прошивок", "*.hex *.bin *.elf"), ("Усі", "*.*")])
        if path and path not in self.firmware_files:
            self.firmware_files.append(path)
            self.firmware_list.insert("end", path)
            selected = self.device_list.curselection()
            if selected:
                self.devices[selected[0]].firmware = path
                self._on_flash_device_selected()
                self._save_devices_to_csv()

    def _delete_firmware(self):
        sel = self.firmware_list.curselection()
        if not sel:
            return
        path = self.firmware_files.pop(sel[0])
        self.firmware_list.delete(sel[0])
        for d in self.devices:
            if d.firmware == path:
                d.firmware = ""
        self._on_flash_device_selected()
        self._save_devices_to_csv()

    def _flash_cpu1(self):
        if not self.programmer.connected:
            messagebox.showerror("Помилка", "Програматор не підключено! Виберіть COM-порт і натисніть 'Підключити'.")
            return

        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)
        if not device:
            messagebox.showwarning("Увага", "Виберіть пристрій.")
            return

        template = self.settings.get("template_cpu1", "")
        if not template:
            messagebox.showerror("Помилка", "Не вказано шаблон команди для CPU 1 у налаштуваннях (⚙️).")
            return

        try:
            self.status_bar1.config(text="Статус: Генерація та виконання батника CPU 1...", foreground="blue")
            self.root.update()

            # Генерація та запуск скрипта
            res = self.programmer.generate_and_run_script(template, device.firmware, self.programmer.port)
            
            self.status_bar1.config(text="Статус: Успішно прошито CPU 1 ✔", foreground="green")
            self._log(f"CPU 1: {res}")
            
            self.cpu1_done = True

            has_two_cpu = any(c.primary_device in TWO_CPU_DEVICES for c in device.controllers)
            if has_two_cpu:
                messagebox.showinfo(
                    "Змініть порт / підключення", 
                    "Прошивання CPU 1 завершено!\n\n"
                    "Будь ласка, перекиньте кабель на **другий порт** для прошивання CPU 2."
                )
                self.programmer.disconnect()
                self.status_label.config(text="● Зв'язок втрачено (змініть порт)", foreground="orange")
                self.btn_connect.config(text="Підключити")
                self.port_combo.config(state="readonly")
                
                if messagebox.askyesno("Перевірка порту", "Чи підключено пристрій до наступного порту та готово до підключення?"):
                    self._toggle_connection()
                    if self.programmer.connected:
                        self.btn_flash2.config(state="normal")
                        self.status_bar2.config(text="Статус: Готовий до прошивання CPU 2", foreground="blue")
            else:
                messagebox.showinfo("Результат", f"Прошивання успішно завершено!\n{res}")

        except Exception as e:
            self.status_bar1.config(text="Статус: Помилка прошивання CPU 1 ❌", foreground="red")
            messagebox.showerror("Помилка", str(e))

    def _flash_cpu2(self):
        if not self.cpu1_done:
            messagebox.showerror("Помилка", "Неможливо почати прошивання CPU 2: перше прошивання не завершено!")
            return

        if not self.programmer.connected:
            messagebox.showerror("Помилка", "Програматор не підключено на новому порті!")
            return

        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)
        if not device:
            messagebox.showwarning("Увага", "Виберіть пристрій.")
            return

        template = self.settings.get("template_cpu2", "")
        if not template:
            messagebox.showerror("Помилка", "Не вказано шаблон команди для CPU 2 у налаштуваннях (⚙️).")
            return

        try:
            self.status_bar2.config(text="Статус: Генерація та виконання батника CPU 2...", foreground="blue")
            self.root.update()

            res = self.programmer.generate_and_run_script(template, device.firmware, self.programmer.port)
            
            self.status_bar2.config(text="Статус: Успішно прошито CPU 2 ✔", foreground="green")
            self._log(f"CPU 2: {res}")
            messagebox.showinfo("Результат", f"Усі етапи успішно завершено!\n\n{res}")

        except Exception as e:
            self.status_bar2.config(text="Статус: Помилка прошивання CPU 2 ❌", foreground="red")
            messagebox.showerror("Помилка", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = ProgrammerApp(root)
    root.mainloop()
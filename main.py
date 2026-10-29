import csv
import json
import subprocess
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass, field

try:
    import serial
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

CSV_FILENAME = "devices.csv"
CONFIG_FILENAME = "config.json"


@dataclass
class Controller:
    primary_device: str
    amperage: tuple[float, float]
    usage: str
    firmware: str = ""  # Прошивка прив'язана 1 до 1 до контролера

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


class Programmer:
    def __init__(self):
        self.port = None
        self.connected = False
        self.serial_conn = None

    def connect(self, port: str):
        if not SERIAL_AVAILABLE:
            raise RuntimeError("Бібліотека pyserial не встановлена! Встановіть її: pip install pyserial")
        
        try:
            self.serial_conn = serial.Serial(port, baudrate=115200, timeout=1)
            self.port = port
            self.connected = True
            return True
        except Exception as e:
            self.connected = False
            self.port = None
            self.serial_conn = None
            raise RuntimeError(f"Не вдалося підключитися до порту {port}.\nПомилка: {e}")

    def disconnect(self):
        if self.serial_conn and self.serial_conn.is_open:
            try:
                self.serial_conn.close()
            except Exception:
                pass
        self.serial_conn = None
        self.port = None
        self.connected = False

    def run_bat_file(self, bat_path: str, firmware: str, port: str):
        if not bat_path or not Path(bat_path).is_file():
            raise RuntimeError(f"Файл батника не знайдено: {bat_path}")

        try:
            result = subprocess.run(
                [bat_path],
                capture_output=True,
                text=True,
                shell=True,
                timeout=40
            )
            if result.returncode != 0:
                raise RuntimeError(f"Помилка виконання скрипта:\n{result.stderr or result.stdout}")
            return result.stdout or "Батник виконано успішно."
        except Exception as e:
            return f"Виконано батник '{bat_path}' для прошивки '{firmware}' (порт {port}). Результат: {e}"


class ProgrammerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Device Programmer - Controller to Firmware 1:1 Binding")
        self.root.geometry("1280x950")
        self.root.minsize(1100, 780)

        self.programmer = Programmer()
        self.devices = []
        
        self.settings = {
            "selected_port": "COM1",
            "bat_filename": "flash_script.bat",
            "cmd_template": "STK500.exe -cUSB -I125kHz -dAtmega64 -s -e -i\"{firmware}\" -pb -vb -O0003 -Sf7fff -fD124 -EFF -FD124 -GFF -lFC -LFC"
        }

        self.current_flash_step = 0
        self.flash_step_widgets = []
        self.settings_visible = False

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
            text="ПРОГРАМАТОР ПРИСТРОЇВ ТА КОНТРОЛЕРІВ",
            font=("Segoe UI", 15, "bold"),
        ).pack(side="left")

        conn_frame = ttk.Frame(header)
        conn_frame.pack(side="left", padx=20)

        self.btn_connect_quick = ttk.Button(conn_frame, text="Підключити", command=self._toggle_connection)
        self.btn_connect_quick.pack(side="left", padx=(0, 10))

        self.status_label = ttk.Label(
            conn_frame, text="● Не підключено", foreground="red"
        )
        self.status_label.pack(side="left", padx=(0, 15))

        self.header_port_label = ttk.Label(
            conn_frame, text="Порт не обрано", font=("Segoe UI", 9, "italic"), foreground="gray"
        )
        self.header_port_label.pack(side="left")

        self.btn_toggle_settings = ttk.Button(
            header, text="⚙️ Налаштування та порти ▼", command=self._toggle_settings_dropdown
        )
        self.btn_toggle_settings.pack(side="right", padx=5)

        # --- СПЛИВАЮЧЕ МЕНЮ НАЛАШТУВАНЬ ---
        self.dropdown_frame = ttk.LabelFrame(self.root, text="Параметри та створення .bat файлу", padding=12)

        f_port = ttk.Frame(self.dropdown_frame)
        f_port.pack(fill="x", pady=(0, 10))
        
        ttk.Label(f_port, text="Вибір COM-порту (1-7):", font=("Segoe UI", 9, "bold"), width=22).pack(side="left")
        
        self.port_combo = ttk.Combobox(f_port, state="readonly", width=15)
        self.port_combo.pack(side="left", padx=5)
        self.port_combo.bind("<<ComboboxSelected>>", self._on_port_selected)
        
        ttk.Button(f_port, text="🔄 Сканувати", command=self._refresh_ports).pack(side="left", padx=5)
        
        self.dropdown_selected_info = ttk.Label(f_port, text="", font=("Segoe UI", 9, "bold"), foreground="blue")
        self.dropdown_selected_info.pack(side="left", padx=15)

        ttk.Separator(self.dropdown_frame, orient="horizontal").pack(fill="x", pady=8)

        f_bat_name = ttk.Frame(self.dropdown_frame)
        f_bat_name.pack(fill="x", pady=4)
        ttk.Label(f_bat_name, text="Назва/шлях батника:", width=20).pack(side="left")
        self.ent_bat_name = ttk.Entry(f_bat_name, width=40)
        self.ent_bat_name.pack(side="left", padx=5)
        self.ent_bat_name.insert(0, self.settings.get("bat_filename", "flash_script.bat"))
        
        ttk.Button(f_bat_name, text="Вибрати файл...", command=self._browse_bat_file).pack(side="left", padx=5)

        ttk.Label(
            self.dropdown_frame, 
            text="Шаблон команди STK500 для створення .bat (змінні: {firmware}, {port}):",
            font=("Segoe UI", 9, "italic")
        ).pack(anchor="w", pady=(8, 2))

        f_in1 = ttk.Frame(self.dropdown_frame)
        f_in1.pack(fill="x", pady=4)
        ttk.Label(f_in1, text="Команда прошивання:", width=20).pack(side="left")
        self.txt_cmd_template = tk.Text(f_in1, height=2, width=70)
        self.txt_cmd_template.pack(side="left", padx=5, fill="x", expand=True)
        self.txt_cmd_template.insert("1.0", self.settings.get("cmd_template", ""))

        f_btns = ttk.Frame(self.dropdown_frame)
        f_btns.pack(fill="x", pady=(10, 0))
        
        ttk.Button(
            f_btns, text="💾 Зберегти налаштування", command=self._save_settings
        ).pack(side="right")

        # --- Основні вкладки ---
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=8)

        self.devices_tab = ttk.Frame(self.notebook, padding=12)
        self.flash_tab = ttk.Frame(self.notebook, padding=12)

        self.notebook.add(self.devices_tab, text="Пристрої, контролери та їх прошивки")
        self.notebook.add(self.flash_tab, text="Прошивання пристрою (покроково)")

        self._build_devices_tab()
        self._build_flash_tab()

        # Журнал та кнопки зберігання CSV
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

    def _toggle_settings_dropdown(self):
        if self.settings_visible:
            self.dropdown_frame.pack_forget()
            self.btn_toggle_settings.config(text="⚙️ Налаштування та порти ▼")
            self.settings_visible = False
        else:
            self.dropdown_frame.pack(fill="x", padx=12, pady=(0, 8), before=self.notebook)
            self.btn_toggle_settings.config(text="⚙️ Налаштування та порти ▲")
            self.settings_visible = True

    def _refresh_ports(self):
        allowed_ports = [f"COM{i}" for i in range(1, 8)]

        if SERIAL_AVAILABLE:
            try:
                found_ports = [p.device for p in serial.tools.list_ports.comports()]
                ports = [p for p in found_ports if p.upper() in allowed_ports]
                if not ports:
                    ports = allowed_ports
            except Exception as e:
                ports = allowed_ports
                self._log(f"Помилка сканування: {e}")
        else:
            ports = allowed_ports

        self.port_combo["values"] = ports
        saved_port = self.settings.get("selected_port", "")

        if saved_port in ports:
            self.port_combo.set(saved_port)
        elif ports:
            self.port_combo.set(ports[0])
        else:
            self.port_combo.set("")

        self._on_port_selected()
        self._log("Доступні COM-порти (COM1–COM7): " + ", ".join(ports))

    def _on_port_selected(self, event=None):
        port = self.port_combo.get().strip()
        if port and port in self.port_combo["values"]:
            self.settings["selected_port"] = port
            self.dropdown_selected_info.config(
                text=f"Обрано: {port}", foreground="blue"
            )
            self.header_port_label.config(
                text=f"Порт: {port}", foreground="blue"
            )
            self._save_config()
        else:
            self.dropdown_selected_info.config(
                text="Порт не обрано", foreground="gray"
            )
            self.header_port_label.config(
                text="Порт не обрано", foreground="gray"
            )

    def _browse_bat_file(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".bat",
            filetypes=[("Batch files", "*.bat"), ("All files", "*.*")],
            title="Виберіть або створіть шлях до батника"
        )
        if path:
            self.ent_bat_name.delete(0, tk.END)
            self.ent_bat_name.insert(0, path)

    def _save_settings(self):
        self.settings["selected_port"] = self.port_combo.get()
        self.settings["bat_filename"] = self.ent_bat_name.get().strip()
        self.settings["cmd_template"] = self.txt_cmd_template.get("1.0", "end-1c").strip()
        
        self._save_config()
        messagebox.showinfo("Успіх", "Налаштування успішно збережено!")
        self._toggle_settings_dropdown()

    def _toggle_connection(self):
        if not self.programmer.connected:
            selected_port = self.port_combo.get()
            if not selected_port:
                messagebox.showerror("Помилка", "Виберіть дійсний COM-порт у налаштуваннях (⚙️).")
                return
            
            try:
                self.programmer.connect(selected_port)
                self.status_label.config(text="● Підключено", foreground="green")
                self.btn_connect_quick.config(text="Відключити")
                self.port_combo.config(state="disabled")
                self._log(f"Успішно підключено до реального порту {selected_port}")
            except Exception as e:
                self.status_label.config(text="● Не підключено", foreground="red")
                messagebox.showerror("Помилка підключення", str(e))
                self._log(f"Помилка підключення до {selected_port}: {e}")
        else:
            self.programmer.disconnect()
            self.status_label.config(text="● Не підключено", foreground="red")
            self.btn_connect_quick.config(text="Підключити")
            self.port_combo.config(state="readonly")
            self._log("Відключено від порту.")

    def _build_devices_tab(self):
        left = ttk.Frame(self.devices_tab)
        left.pack(side="left", fill="y", padx=(0, 10))

        ttk.Label(left, text="Пристрої (напр. CPO150)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 5))

        self.device_list = tk.Listbox(left, height=18, width=28)
        self.device_list.pack(fill="y", expand=True, pady=(0, 5))
        self.device_list.bind("<<ListboxSelect>>", self._on_device_selected)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x")
        ttk.Button(btn_frame, text="Додати пристрій", command=self._add_device).pack(side="left", expand=True, fill="x", padx=(0, 2))
        ttk.Button(btn_frame, text="Видалити", command=self._delete_device).pack(side="left", expand=True, fill="x", padx=(2, 0))

        right = ttk.LabelFrame(self.devices_tab, text="Контролери та прошивки для вибраного пристрою", padding=12)
        right.pack(side="right", fill="both", expand=True)

        ttk.Label(right, text="Назва пристрою:").pack(anchor="w")
        self.device_name_var = tk.StringVar()
        name_entry = ttk.Entry(right, textvariable=self.device_name_var)
        name_entry.pack(fill="x", pady=(2, 10))
        name_entry.bind("<FocusOut>", lambda e: self._save_device_name())
        name_entry.bind("<Return>", lambda e: self._save_device_name())

        # Фрейм додавання нового контролера
        add_ctrl_frame = ttk.LabelFrame(right, text="Додати новий контролер та прошивку", padding=10)
        add_ctrl_frame.pack(fill="x", pady=(0, 10))

        grid_f = ttk.Frame(add_ctrl_frame)
        grid_f.pack(fill="x", pady=(0, 5))

        ttk.Label(grid_f, text="Тип контролера:").grid(row=0, column=0, sticky="w", padx=2)
        self.new_type_var = tk.StringVar(value=PRIMARY_DEVICES[0])
        ttk.Combobox(grid_f, textvariable=self.new_type_var, values=PRIMARY_DEVICES, state="readonly", width=22).grid(row=0, column=1, padx=2, sticky="ew")

        ttk.Label(grid_f, text="Призначення:").grid(row=0, column=2, sticky="w", padx=2)
        self.new_usage_var = tk.StringVar(value=USAGES[0])
        ttk.Combobox(grid_f, textvariable=self.new_usage_var, values=USAGES, state="readonly", width=18).grid(row=0, column=3, padx=2, sticky="ew")

        grid_f2 = ttk.Frame(add_ctrl_frame)
        grid_f2.pack(fill="x", pady=(5, 5))

        ttk.Label(grid_f2, text="Струм (A): мін").pack(side="left", padx=2)
        self.new_low_var = tk.StringVar(value="1.0")
        ttk.Entry(grid_f2, textvariable=self.new_low_var, width=6).pack(side="left", padx=2)

        ttk.Label(grid_f2, text="макс").pack(side="left", padx=2)
        self.new_high_var = tk.StringVar(value="5.0")
        ttk.Entry(grid_f2, textvariable=self.new_high_var, width=6).pack(side="left", padx=2)

        grid_fw = ttk.Frame(add_ctrl_frame)
        grid_fw.pack(fill="x", pady=(5, 5))

        ttk.Label(grid_fw, text="Файл прошивки (.hex):").pack(side="left", padx=2)
        self.new_fw_var = tk.StringVar()
        ttk.Entry(grid_fw, textvariable=self.new_fw_var, state="readonly").pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(grid_fw, text="Обзори...", command=self._browse_new_firmware).pack(side="left", padx=2)

        ttk.Button(add_ctrl_frame, text="+ Додати контролер до пристрою", command=self._add_controller).pack(anchor="e", pady=(5, 0))

        # Таблиця контролерів пристрою
        ttk.Label(right, text="Список контролерів та їх прошивок (1 до 1):", font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(5, 2))
        
        columns = ("type", "usage", "amperage", "firmware")
        self.tree = ttk.Treeview(right, columns=columns, show="headings", height=8)
        self.tree.heading("type", text="Тип контролера")
        self.tree.heading("usage", text="Призначення")
        self.tree.heading("amperage", text="Діапазон струму")
        self.tree.heading("firmware", text="Прив'язана прошивка (Файл)")
        
        self.tree.column("type", width=180, anchor="w")
        self.tree.column("usage", width=140, anchor="w")
        self.tree.column("amperage", width=110, anchor="center")
        self.tree.column("firmware", width=250, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(0, 8))

        f_tbl_btns = ttk.Frame(right)
        f_tbl_btns.pack(fill="x")
        ttk.Button(f_tbl_btns, text="Змінити прошивку для вибраного", command=self._change_controller_firmware).pack(side="left")
        ttk.Button(f_tbl_btns, text="Видалити вибраний контролер", command=self._delete_controller).pack(side="right")

    def _build_flash_tab(self):
        ttk.Label(self.flash_tab, text="Підготовка до прошивання за пристроями", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        
        f_top = ttk.Frame(self.flash_tab)
        f_top.pack(fill="x", pady=(0, 10))

        ttk.Label(f_top, text="Виберіть пристрій для прошивання:", font=("Segoe UI", 9, "bold")).pack(side="left", padx=(0, 10))
        self.flash_device_var = tk.StringVar()
        self.flash_device_combo = ttk.Combobox(f_top, textvariable=self.flash_device_var, state="readonly", width=30)
        self.flash_device_combo.pack(side="left")
        self.flash_device_combo.bind("<<ComboboxSelected>>", self._on_flash_device_selected)

        # Контейнер для покрокових блоків контролерів (динамічно створюється)
        self.flash_steps_container = ttk.Frame(self.flash_tab)
        self.flash_steps_container.pack(fill="both", expand=True)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _save_devices_to_csv(self):
        try:
            with open(CSV_FILENAME, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(["DeviceName", "PrimaryDevice", "Usage", "AmperageLow", "AmperageHigh", "Firmware"])
                
                for device in self.devices:
                    if not device.controllers:
                        writer.writerow([device.name, "", "", "", "", ""])
                    for c in device.controllers:
                        writer.writerow([
                            device.name,
                            c.primary_device,
                            c.usage,
                            c.amperage[0],
                            c.amperage[1],
                            c.firmware
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
                    p_dev = row["PrimaryDevice"]
                    usage = row["Usage"]
                    low = row["AmperageLow"]
                    high = row["AmperageHigh"]
                    fw = row.get("Firmware", "")

                    if name not in loaded_devices:
                        loaded_devices[name] = Device(name=name, controllers=[])

                    if p_dev and usage and low and high:
                        try:
                            ctrl = Controller(
                                primary_device=p_dev,
                                usage=usage,
                                amperage=(float(low), float(high)),
                                firmware=fw
                            )
                            loaded_devices[name].controllers.append(ctrl)
                        except ValueError:
                            pass

            self.devices = list(loaded_devices.values())
            self._refresh_devices()
            self._log(f"Дані успішно завантажено з файлу {CSV_FILENAME}")
        except Exception as e:
            self._log(f"Помилка завантаження CSV: {e}")

    def _on_close(self):
        self._save_devices_to_csv()
        self._save_config()
        self.root.destroy()

    def _add_device(self):
        base_name = "CPO150"
        name = base_name
        counter = 1
        while any(d.name == name for d in self.devices):
            counter += 1
            name = f"{base_name}_{counter}"

        device = Device(name=name)
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

    def _browse_new_firmware(self):
        path = filedialog.askopenfilename(filetypes=[("Hex files", "*.hex"), ("Усі файли", "*.*")])
        if path:
            self.new_fw_var.set(path)

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
            fw_name = Path(c.firmware).name if c.firmware else "❌ Відсутня"
            self.tree.insert("", "end", values=(c.primary_device, c.usage, f"{c.amperage[0]} – {c.amperage[1]} A", fw_name))

    def _add_controller(self):
        selected = self.device_list.curselection()
        if not selected:
            messagebox.showwarning("Увага", "Спочатку виберіть пристрій зі списку ліворуч.")
            return

        try:
            low = float(self.new_low_var.get().replace(",", "."))
            high = float(self.new_high_var.get().replace(",", "."))
            fw = self.new_fw_var.get().strip()
            
            ctrl = Controller(
                primary_device=self.new_type_var.get(),
                amperage=(low, high),
                usage=self.new_usage_var.get(),
                firmware=fw
            )
        except (ValueError, TypeError) as e:
            messagebox.showerror("Помилка", str(e))
            return

        device = self.devices[selected[0]]
        device.controllers.append(ctrl)
        self.new_fw_var.set("") # скинути поле після додавання
        self._refresh_tree(device)
        self._save_devices_to_csv()
        self._on_flash_device_selected()
        self._log(f"Додано контролер ({ctrl.primary_device}) з прошивкою до пристрою {device.name}")

    def _change_controller_firmware(self):
        selected_device = self.device_list.curselection()
        if not selected_device:
            return
        device = self.devices[selected_device[0]]

        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Увага", "Виберіть контролер у таблиці для зміни його прошивки.")
            return

        idx = self.tree.index(selected_item[0])
        ctrl = device.controllers[idx]

        path = filedialog.askopenfilename(filetypes=[("Hex files", "*.hex"), ("Усі файли", "*.*")])
        if path:
            ctrl.firmware = path
            self._refresh_tree(device)
            self._save_devices_to_csv()
            self._on_flash_device_selected()
            self._log(f"Оновлено прошивку для контролера #{idx+1} пристрою {device.name}")

    def _delete_controller(self):
        selected = self.device_list.curselection()
        if not selected:
            return
        device = self.devices[selected[0]]
        
        selected_item = self.tree.selection()
        if not selected_item:
            messagebox.showwarning("Увага", "Виберіть контролер у таблиці для видалення.")
            return

        idx = self.tree.index(selected_item[0])
        device.controllers.pop(idx)
        self._refresh_tree(device)
        self._save_devices_to_csv()
        self._on_flash_device_selected()
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
        """Динамічно будує блоки прошивання під всі контролери вибраного пристрою."""
        for child in self.flash_steps_container.winfo_children():
            child.destroy()

        self.flash_step_widgets.clear()
        self.current_flash_step = 0

        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)

        if not device or not device.controllers:
            ttk.Label(
                self.flash_steps_container, 
                text="У вибраному пристрої немає доданих контролерів або пристрій не вибрано.", 
                foreground="red"
            ).pack(anchor="w", pady=10)
            return

        # Будуємо інтерфейс для кожного контролера у пристрої
        for idx, ctrl in enumerate(device.controllers):
            step_num = idx + 1
            frame = ttk.LabelFrame(
                self.flash_steps_container, 
                text=f"Крок {step_num}: Контролер '{ctrl.primary_device}' ({ctrl.usage}, {ctrl.amperage[0]}-{ctrl.amperage[1]}A)", 
                padding=10
            )
            frame.pack(fill="x", pady=5)

            fw_name = Path(ctrl.firmware).name if ctrl.firmware else "❌ Прошивка відсутня!"
            lbl_fw = ttk.Label(frame, text=f"Файл прошивки: {fw_name}", font=("Segoe UI", 9, "bold"))
            lbl_fw.pack(anchor="w", pady=(0, 5))

            f_act = ttk.Frame(frame)
            f_act.pack(fill="x")

            status_lbl = ttk.Label(
                f_act, 
                text="Статус: Очікування" if step_num == 1 else "Статус: Заблоковано (чекає попередній крок)", 
                foreground="gray"
            )
            status_lbl.pack(side="left")

            btn_flash = ttk.Button(
                f_act, 
                text=f"Прошити контролер #{step_num}", 
                state="normal" if step_num == 1 else "disabled",
                command=lambda i=idx: self._flash_controller_step(i)
            )
            btn_flash.pack(side="right")

            self.flash_step_widgets.append({
                "status": status_lbl,
                "button": btn_flash,
                "controller": ctrl
            })

    def _generate_temp_bat(self, firmware_path: str) -> str:
        bat_name = self.settings.get("bat_filename", "flash_script.bat")
        cmd_template = self.settings.get("cmd_template", "")
        command = cmd_template.replace("{firmware}", firmware_path).replace("{port}", self.programmer.port or "COM1")

        bat_content = (
            "@ECHO OFF\n"
            "chcp 65001 >nul\n"
            "SET PATH=C:\\Program Files\\Atmel\\AVR Tools\\STK500;%PATH%\n\n"
            f"{command}\n\n"
            "PAUSE\n"
        )
        with open(bat_name, "w", encoding="cp1251") as f:
            f.write(bat_content)
        return bat_name

    def _flash_controller_step(self, step_idx: int):
        if not self.programmer.connected:
            messagebox.showerror("Помилка", "Програматор не підключено! Оберіть порт у налаштуваннях (⚙️) і натисніть 'Підключити'.")
            return

        widget_info = self.flash_step_widgets[step_idx]
        ctrl = widget_info["controller"]

        if not ctrl.firmware or not Path(ctrl.firmware).is_file():
            messagebox.showerror("Помилка", f"Файл прошивки для контролера #{step_idx+1} не знайдено або не вказано!")
            return

        try:
            widget_info["status"].config(text=f"Статус: Виконання STK500 для контролера #{step_idx+1}...", foreground="blue")
            self.root.update()

            bat_file = self._generate_temp_bat(ctrl.firmware)
            res = self.programmer.run_bat_file(bat_file, ctrl.firmware, self.programmer.port)

            widget_info["status"].config(text=f"Статус: Успішно прошито ✔", foreground="green")
            widget_info["button"].config(state="disabled")
            self._log(f"Контролер #{step_idx+1} ({ctrl.primary_device}): {res}")

            next_step = step_idx + 1
            if next_step < len(self.flash_step_widgets):
                messagebox.showinfo(
                    "Переключіть порт", 
                    f"Прошивання контролера #{step_idx+1} завершено!\n\n"
                    f"Будь ласка, підключіть кабель до **наступного порту / контролера #{next_step+1}**."
                )
                self.programmer.disconnect()
                self.status_label.config(text="● Не підключено", foreground="red")
                self.btn_connect_quick.config(text="Підключити")
                self.port_combo.config(state="readonly")

                if messagebox.askyesno("Перевірка підключення", f"Чи підключено кабель до контролера #{next_step+1} та готово до підключення?"):
                    self._toggle_connection()
                    if self.programmer.connected:
                        next_widget = self.flash_step_widgets[next_step]
                        next_widget["button"].config(state="normal")
                        next_widget["status"].config(text="Статус: Готово до прошивання", foreground="blue")
            else:
                messagebox.showinfo("Успіх!", "Усі контролери цього пристрою успішно прошито!")

        except Exception as e:
            widget_info["status"].config(text="Статус: Помилка прошивання ❌", foreground="red")
            messagebox.showerror("Помилка", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = ProgrammerApp(root)
    root.mainloop()
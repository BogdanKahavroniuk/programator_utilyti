import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from dataclasses import dataclass, field


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
        self.connected = False

    def check_connection(self):
        self.connected = False
        return self.connected

    def program(self, device: Device):
        if not self.connected:
            raise RuntimeError("Програматор не підключений.")
        if not device.firmware:
            raise RuntimeError("Для пристрою не вибрано прошивку.")

        total_cpus = sum(
            2 if c.primary_device in TWO_CPU_DEVICES else 1
            for c in device.controllers
        )

        return (
            f"Демонстрація: підготовлено прошивання "
            f"{total_cpus} CPU для пристрою {device.name} "
            f"({len(device.controllers)} контролер(ів)).\n"
            f"Файл: {device.firmware}"
        )


class ProgrammerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Device Programmer")
        self.root.geometry("1100x720")
        self.root.minsize(900, 600)

        self.programmer = Programmer()
        self.devices = []
        self.firmware_files = []

        self._build_ui()
        self._load_devices_from_csv()  # Автоматичне завантаження при старті
        self._refresh_devices()

        # Збереження при закритті вікна
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        # Верхня панель
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")

        ttk.Label(
            header,
            text="КЕРУВАННЯ ПРОШИВАННЯМ",
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left")

        self.status_label = ttk.Label(
            header, text="● Не підключено", foreground="red"
        )
        self.status_label.pack(side="right", padx=10)

        ttk.Button(
            header, text="Перевірити програматор", command=self._check_connection
        ).pack(side="right")

        # Вкладки
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=8)

        self.devices_tab = ttk.Frame(notebook, padding=12)
        self.firmware_tab = ttk.Frame(notebook, padding=12)
        self.flash_tab = ttk.Frame(notebook, padding=12)

        notebook.add(self.devices_tab, text="Пристрої та контролери")
        notebook.add(self.firmware_tab, text="Прошивки")
        notebook.add(self.flash_tab, text="Прошивання")

        self._build_devices_tab()
        self._build_firmware_tab()
        self._build_flash_tab()

        # Журнал та кнопка збереження
        bottom_frame = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        bottom_frame.pack(fill="x")

        log_frame = ttk.LabelFrame(bottom_frame, text="Журнал", padding=8)
        log_frame.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.log_text = tk.Text(log_frame, height=4, state="disabled", wrap="word")
        self.log_text.pack(fill="x")

        # Кнопки збереження/завантаження вручну
        file_btns_frame = ttk.Frame(bottom_frame)
        file_btns_frame.pack(side="right", fill="y")

        ttk.Button(
            file_btns_frame, text="💾 Зберегти в CSV", command=self._save_devices_to_csv
        ).pack(fill="x", expand=True, pady=(0, 4))
        ttk.Button(
            file_btns_frame, text="📂 Завантажити з CSV", command=self._load_devices_from_csv
        ).pack(fill="x", expand=True)

        self._log("Програму запущено.")

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
        ttk.Label(self.flash_tab, text="Підготовка до прошивання", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(self.flash_tab, text="Виберіть пристрій:").pack(anchor="w")

        self.flash_device_var = tk.StringVar()
        self.flash_device_combo = ttk.Combobox(self.flash_tab, textvariable=self.flash_device_var, state="readonly")
        self.flash_device_combo.pack(fill="x", pady=(3, 12))
        self.flash_device_combo.bind("<<ComboboxSelected>>", self._update_flash_info)

        self.flash_info = ttk.Label(self.flash_tab, text="", justify="left")
        self.flash_info.pack(anchor="w", pady=8)

        ttk.Button(self.flash_tab, text="ПРОШИТИ", command=self._flash).pack(anchor="w", pady=15)

    def _log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _check_connection(self):
        connected = self.programmer.check_connection()
        self.status_label.config(
            text="● Підключено" if connected else "● Не підключено",
            foreground="green" if connected else "red"
        )
        self._log("Перевірка з'єднання програматора.")

    def _save_devices_to_csv(self):
        """Зберігає список пристроїв у CSV файл."""
        try:
            with open(CSV_FILENAME, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                # Заголовок: Назва пристрою, Шлях до прошивки, Тип контролера, Призначення, Мін струм, Макс струм
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
        """Завантажує список пристроїв з CSV файлу."""
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
            
            # Також відновлюємо список файлів прошивок, якщо вони є у пристроях
            for d in self.devices:
                if d.firmware and d.firmware not in self.firmware_files:
                    self.firmware_files.append(d.firmware)
                    self.firmware_list.insert("end", d.firmware)

            self._refresh_devices()
            self._log(f"Дані успішно завантажено з файлу {CSV_FILENAME}")
        except Exception as e:
            self._log(f"Помилка завантаження CSV: {e}")

    def _on_close(self):
        """Автозбереження при закритті програми."""
        self._save_devices_to_csv()
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
        self._update_flash_info()

    def _add_firmware(self):
        path = filedialog.askopenfilename(filetypes=[("Файли прошивок", "*.hex *.bin *.elf"), ("Усі", "*.*")])
        if path and path not in self.firmware_files:
            self.firmware_files.append(path)
            self.firmware_list.insert("end", path)
            selected = self.device_list.curselection()
            if selected:
                self.devices[selected[0]].firmware = path
                self._update_flash_info()
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
        self._update_flash_info()
        self._save_devices_to_csv()

    def _update_flash_info(self, event=None):
        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)
        if not device:
            self.flash_info.config(text="Виберіть пристрій.")
            return

        total_cpus = sum(2 if c.primary_device in TWO_CPU_DEVICES else 1 for c in device.controllers)
        ctrl_text = "\n".join([f"  • {c.primary_device} ({c.usage}, {c.amperage[0]}–{c.amperage[1]}A)" for c in device.controllers])

        self.flash_info.config(
            text=f"Пристрій: {device.name}\n"
                 f"Контролери:\n{ctrl_text}\n"
                 f"Всього CPU: {total_cpus}\n"
                 f"Прошивка: {device.firmware or 'Не вибрана'}"
        )

    def _flash(self):
        name = self.flash_device_var.get()
        device = next((d for d in self.devices if d.name == name), None)
        if not device:
            messagebox.showwarning("Увага", "Виберіть пристрій.")
            return
        try:
            res = self.programmer.program(device)
            messagebox.showinfo("Успіх", res)
            self._log(res)
        except Exception as e:
            messagebox.showerror("Помилка", str(e))


if __name__ == "__main__":
    root = tk.Tk()
    app = ProgrammerApp(root)
    root.mainloop()
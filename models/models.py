

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from dataclasses import dataclass
from pathlib import Path


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

# Пристрої, для яких передбачено прошивання двох CPU.
TWO_CPU_DEVICES = {"Стандарт2", "Стандарт21"}


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
    controller: Controller
    firmware: str = ""


class Programmer:
    """Інтерфейс для майбутнього підключення реального програматора."""

    def __init__(self):
        self.connected = False

    def check_connection(self):
        # TODO: реалізувати перевірку конкретного програматора.
        # Наразі підключення не перевіряється фізично.
        self.connected = False
        return self.connected

    def program(self, device: Device):
        if not self.connected:
            raise RuntimeError("Програматор не підключений.")

        if not device.firmware:
            raise RuntimeError("Для пристрою не вибрано прошивку.")

        # TODO: виклик реальної утиліти/API програматора.
        cpu_count = 2 if device.name in TWO_CPU_DEVICES else 1

        return (
            f"Демонстрація: підготовлено прошивання "
            f"{cpu_count} CPU для {device.name}.\n"
            f"Файл: {device.firmware}\n"
            f"Реальне прошивання ще не реалізовано."
        )


class ProgrammerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Device Programmer")
        self.root.geometry("1050x700")
        self.root.minsize(850, 600)

        self.programmer = Programmer()
        self.devices = []
        self.firmware_files = []

        self._build_ui()
        self._refresh_devices()

    def _build_ui(self):
        # Верхня панель
        header = ttk.Frame(self.root, padding=12)
        header.pack(fill="x")

        ttk.Label(
            header,
            text="КЕРУВАННЯ ПРОШИВАННЯМ",
            font=("Segoe UI", 17, "bold"),
        ).pack(side="left")

        self.status_label = ttk.Label(
            header,
            text="● Не підключено",
            foreground="red",
        )
        self.status_label.pack(side="right", padx=10)

        ttk.Button(
            header,
            text="Перевірити програматор",
            command=self._check_connection,
        ).pack(side="right")

        # Основні вкладки
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

        # Журнал
        log_frame = ttk.LabelFrame(
            self.root, text="Журнал операцій", padding=8
        )
        log_frame.pack(fill="x", padx=12, pady=(0, 12))

        self.log_text = tk.Text(
            log_frame, height=6, state="disabled", wrap="word"
        )
        self.log_text.pack(fill="x")

        self._log("Програму запущено.")

    def _build_devices_tab(self):
        left = ttk.Frame(self.devices_tab)
        left.pack(side="left", fill="both", expand=True)

        ttk.Label(
            left, text="Зареєстровані пристрої",
            font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", pady=(0, 8))

        self.device_list = tk.Listbox(left, height=15)
        self.device_list.pack(fill="both", expand=True)
        self.device_list.bind(
            "<<ListboxSelect>>", self._on_device_selected
        )

        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=8)

        ttk.Button(
            buttons, text="Додати пристрій",
            command=self._add_device
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            buttons, text="Видалити",
            command=self._delete_device
        ).pack(side="left")

        # Форма контролера
        right = ttk.LabelFrame(
            self.devices_tab, text="Параметри пристрою", padding=12
        )
        right.pack(side="right", fill="y", padx=(15, 0))

        ttk.Label(right, text="Назва пристрою").pack(anchor="w")

        self.device_name_var = tk.StringVar()
        ttk.Entry(
            right, textvariable=self.device_name_var, width=30
        ).pack(fill="x", pady=(3, 10))

        ttk.Label(right, text="Тип контролера").pack(anchor="w")

        self.controller_type_var = tk.StringVar(
            value=PRIMARY_DEVICES[0]
        )
        ttk.Combobox(
            right,
            textvariable=self.controller_type_var,
            values=PRIMARY_DEVICES,
            state="readonly",
            width=27,
        ).pack(fill="x", pady=(3, 10))

        ttk.Label(right, text="Призначення").pack(anchor="w")

        self.usage_var = tk.StringVar(value=USAGES[0])
        ttk.Combobox(
            right,
            textvariable=self.usage_var,
            values=USAGES,
            state="readonly",
        ).pack(fill="x", pady=(3, 10))

        ttk.Label(right, text="Нижня межа струму (A)").pack(anchor="w")
        self.low_var = tk.StringVar(value="1.0")
        ttk.Entry(right, textvariable=self.low_var).pack(
            fill="x", pady=(3, 10)
        )

        ttk.Label(right, text="Верхня межа струму (A)").pack(anchor="w")
        self.high_var = tk.StringVar(value="5.0")
        ttk.Entry(right, textvariable=self.high_var).pack(
            fill="x", pady=(3, 10)
        )

        ttk.Button(
            right, text="Зберегти параметри",
            command=self._save_device
        ).pack(fill="x", pady=8)

    def _build_firmware_tab(self):
        ttk.Label(
            self.firmware_tab,
            text="Файли прошивок",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            self.firmware_tab,
            text="Додай файл прошивки та прив'яжи його до пристрою."
        ).pack(anchor="w", pady=5)

        self.firmware_list = tk.Listbox(
            self.firmware_tab, height=15
        )
        self.firmware_list.pack(fill="both", expand=True, pady=8)

        buttons = ttk.Frame(self.firmware_tab)
        buttons.pack(fill="x")

        ttk.Button(
            buttons, text="Додати файл",
            command=self._add_firmware
        ).pack(side="left", padx=(0, 5))

        ttk.Button(
            buttons, text="Видалити файл зі списку",
            command=self._delete_firmware
        ).pack(side="left")

        ttk.Label(
            self.firmware_tab,
            text="Файл не змінюється і не прошивається під час додавання."
        ).pack(anchor="w", pady=10)

    def _build_flash_tab(self):
        ttk.Label(
            self.flash_tab,
            text="Підготовка до прошивання",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w", pady=(0, 12))

        ttk.Label(self.flash_tab, text="Пристрій").pack(anchor="w")

        self.flash_device_var = tk.StringVar()
        self.flash_device_combo = ttk.Combobox(
            self.flash_tab,
            textvariable=self.flash_device_var,
            state="readonly",
        )
        self.flash_device_combo.pack(fill="x", pady=(3, 12))
        self.flash_device_combo.bind(
            "<<ComboboxSelected>>", self._update_flash_info
        )

        self.flash_info = ttk.Label(
            self.flash_tab,
            text="Вибери пристрій для перегляду параметрів.",
            justify="left",
        )
        self.flash_info.pack(anchor="w", pady=8)

        ttk.Button(
            self.flash_tab,
            text="ПРОШИТИ",
            command=self._flash,
        ).pack(anchor="w", pady=15)

        self.progress = ttk.Progressbar(
            self.flash_tab, mode="indeterminate"
        )
        self.progress.pack(fill="x", pady=5)

        ttk.Label(
            self.flash_tab,
            text=(
                "Увага: зараз кнопка виконує лише перевірки та "
                "демонстраційну підготовку. Реальний запис у CPU "
                "потребує драйвера/API програматора."
            ),
            wraplength=750,
        ).pack(anchor="w", pady=12)

    def _log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _check_connection(self):
        connected = self.programmer.check_connection()

        if connected:
            self.status_label.config(
                text="● Підключено", foreground="green"
            )
        else:
            self.status_label.config(
                text="● Не підключено", foreground="red"
            )

        self._log(
            "Перевірка програматора: "
            + ("підключено." if connected else
               "не підтверджено (перевірка ще не реалізована).")
        )

    def _add_device(self):
        name = self.device_name_var.get().strip()

        if not name:
            messagebox.showerror("Помилка", "Введи назву пристрою.")
            return

        if any(d.name == name for d in self.devices):
            messagebox.showerror(
                "Помилка", "Пристрій із такою назвою вже існує."
            )
            return

        self._save_device()

    def _save_device(self):
        name = self.device_name_var.get().strip()

        if not name:
            messagebox.showerror("Помилка", "Введи назву пристрою.")
            return

        try:
            low = float(self.low_var.get().replace(",", "."))
            high = float(self.high_var.get().replace(",", "."))

            controller = Controller(
                primary_device=self.controller_type_var.get(),
                amperage=(low, high),
                usage=self.usage_var.get(),
            )
        except (ValueError, TypeError) as error:
            messagebox.showerror("Некоректні дані", str(error))
            return

        selected = self.device_list.curselection()

        if selected:
            index = selected[0]
            old_device = self.devices[index]

            if any(
                i != index and d.name == name
                for i, d in enumerate(self.devices)
            ):
                messagebox.showerror(
                    "Помилка", "Така назва вже використовується."
                )
                return

            old_device.name = name
            old_device.controller = controller
            device = old_device
            self._log(f"Оновлено пристрій: {name}")
        else:
            device = Device(name=name, controller=controller)
            self.devices.append(device)
            self._log(f"Додано пристрій: {name}")

        self._refresh_devices()
        self._select_device(device)

    def _select_device(self, device):
        index = self.devices.index(device)
        self.device_list.selection_clear(0, "end")
        self.device_list.selection_set(index)
        self.device_list.activate(index)
        self._on_device_selected()

    def _on_device_selected(self, event=None):
        selected = self.device_list.curselection()
        if not selected:
            return

        device = self.devices[selected[0]]
        controller = device.controller

        self.device_name_var.set(device.name)
        self.controller_type_var.set(controller.primary_device)
        self.usage_var.set(controller.usage)
        self.low_var.set(str(controller.amperage[0]))
        self.high_var.set(str(controller.amperage[1]))

    def _delete_device(self):
        selected = self.device_list.curselection()
        if not selected:
            messagebox.showwarning(
                "Увага", "Спочатку вибери пристрій."
            )
            return

        device = self.devices.pop(selected[0])
        self._refresh_devices()
        self._log(f"Видалено пристрій: {device.name}")

    def _refresh_devices(self):
        self.device_list.delete(0, "end")

        for device in self.devices:
            self.device_list.insert(
                "end",
                f"{device.name} | {device.controller.primary_device}"
            )

        names = [device.name for device in self.devices]
        self.flash_device_combo["values"] = names

        if self.flash_device_var.get() not in names:
            self.flash_device_var.set(names[0] if names else "")

        self._update_flash_info()

    def _add_firmware(self):
        path = filedialog.askopenfilename(
            title="Вибери файл прошивки",
            filetypes=[
                ("Файли прошивок", "*.hex *.bin *.elf *.srec *.mot"),
                ("Усі файли", "*.*"),
            ],
        )

        if not path:
            return

        if path not in self.firmware_files:
            self.firmware_files.append(path)
            self.firmware_list.insert("end", path)
            self._log(f"Додано файл прошивки: {path}")

        # Прив'язуємо вибраний файл до поточного пристрою.
        selected = self.device_list.curselection()
        if selected:
            device = self.devices[selected[0]]
            device.firmware = path
            self._log(
                f"Прошивку прив'язано до пристрою {device.name}"
            )
            self._update_flash_info()

    def _delete_firmware(self):
        selected = self.firmware_list.curselection()
        if not selected:
            messagebox.showwarning(
                "Увага", "Вибери файл у списку."
            )
            return

        path = self.firmware_files.pop(selected[0])
        self.firmware_list.delete(selected[0])

        # Видалення зі списку не видаляє файл із диска.
        for device in self.devices:
            if device.firmware == path:
                device.firmware = ""

        self._update_flash_info()
        self._log(f"Файл видалено зі списку: {path}")

    def _get_flash_device(self):
        name = self.flash_device_var.get()
        return next(
            (device for device in self.devices if device.name == name),
            None,
        )

    def _update_flash_info(self, event=None):
        device = self._get_flash_device()

        if device is None:
            self.flash_info.config(text="Спочатку додай пристрій.")
            return

        controller = device.controller
        cpu_count = 2 if device.name in TWO_CPU_DEVICES else 1

        self.flash_info.config(
            text=(
                f"Назва: {device.name}\n"
                f"Тип контролера: {controller.primary_device}\n"
                f"Призначення: {controller.usage}\n"
                f"Струм: {controller.amperage[0]}–"
                f"{controller.amperage[1]} A\n"
                f"Кількість CPU за налаштуванням: {cpu_count}\n"
                f"Прошивка: {device.firmware or 'Не вибрана'}"
            )
        )

    def _flash(self):
        device = self._get_flash_device()

        if device is None:
            messagebox.showwarning(
                "Увага", "Вибери або створи пристрій."
            )
            return

        if not self.programmer.connected:
            messagebox.showerror(
                "Немає підключення",
                "Програматор не підключений. "
                "Реальну перевірку потрібно реалізувати для твого обладнання.",
            )
            self._log("Прошивання скасовано: немає підтвердженого підключення.")
            return

        if not device.firmware or not Path(device.firmware).is_file():
            messagebox.showerror(
                "Помилка", "Вибери наявний файл прошивки."
            )
            return

        try:
            result = self.programmer.program(device)
            self._log(result)
            messagebox.showinfo("Результат", result)
        except RuntimeError as error:
            messagebox.showerror("Помилка прошивання", str(error))
            self._log(f"Помилка: {error}")


if __name__ == "__main__":
    root = tk.Tk()
    app = ProgrammerApp(root)
    root.mainloop()









        
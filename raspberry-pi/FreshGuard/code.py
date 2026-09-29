import time
import board
import busio
import RPi.GPIO as GPIO
import adafruit_dht
from RPLCD.i2c import CharLCD
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
import firebase_admin
from firebase_admin import credentials, db as firebase_db

# ----------------- GPIO / LED Pin Setup -----------------
# Chart ke mutabiq BCM GPIO Numbers:
GREEN_LED_PIN = 27   # Pin 13 (GPIO 27)
RED_LED_PIN = 23     # Pin 16 (GPIO 23)
YELLOW_LED_PIN = 22  # Pin 15 (GPIO 22)

GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(GREEN_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RED_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(YELLOW_LED_PIN, GPIO.OUT, initial=GPIO.LOW)  # Filhal OFF rahegi

def update_leds(status):
    """LED indicators based on health status"""
    if status == "HEALTHY":
        GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
        GPIO.output(RED_LED_PIN, GPIO.LOW)
    else:  # NEEDS_ATTENTION ya koi issue
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        GPIO.output(RED_LED_PIN, GPIO.HIGH)

# ----------------- Firebase Configuration -----------------
FIREBASE_DB_URL = "https://fresh-guard-aaaf8-default-rtdb.firebaseio.com"
FIREBASE_DEVICE_ID = "pi-01"
FIREBASE_INTERVAL = 15

FIREBASE_CRED_DICT = {
  "type": "service_account",
  "project_id": "fresh-guard-aaaf8",
  "private_key_id": "37ad0887431f210013a9b4cfbf872e60bc0fc369",
  "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQCz4CFWb0Yzi0sL\ni//mOhf8FvuvDqIp6fy9MafiAiTkdjdZhpAmHJAfRm5XhJwLAncbaAx3ycRkKhkq\nEFQfe/W8fa9B5hImp4C412z1cp/gF7tmxYlBmouwdwycFOJErM7Ea1n28DufcTsY\nF1zTg2PJb8QOxPzt7QSLETkALJs0KALg3t4SsV4wWZ8lKs6RY6xz1CaDxyo4OFF0\n+twauQp5gIOyOzEgXmC1ZLdrZpAaWx1IYDpB/IwfOYQ66p5wKPKgxTDU3XmEUCFf\nz6PfqbET8t1TO99EzH7sptUTVSKRDPvwbnUtKujpDqn7LoZDw7Hrz7rHx2lSGbeF\n9A0DfO87AgMBAAECggEARAWUpdqjqhdZdE7noVlDu7W3TO6UPZR6WtOd4Lad2/Wm\nncjo1zjC+cjJLnh8CB/RCgCxglU/Wv+ej40oOtXGSpcfASUvpQWABKaW0kUcF4Lx\n//3gl3oJrFyA3L97B6xv7tCH733Olk+cINKo7GXKBSGqe0lcOt+AcdS8AQhdUv3R\nQyiRj0qQLBL+dLrl3khd4wx6AezjP4pS+muZh6Z9qy9ujmLpasCd7BqUEu26Y848\n9GIgGwAdHcUL8tIKOHj8eqb3njsyI+kY4R2IrWL1v8ZyTiQDzkUjesEDnkFCpcPS\na9xvnuOoTR7ibkRKquKfcZFzMkzrVU5HiQC2aHpdPQKBgQDvLz+k7XkpxyT7Dg1p\nL8jkV9B8icjtmtsZCmOP4vZqKCcLkjEAJMkQJmNyvpNGGcvBYqdncY9cZeeaTf4g\nmjm3CDs3dJMggZHJxdCgjpY9Om8Px+scZIUGhCyyBhHPgqj+gA+tVyEdQtzfSPaC\nxr0Mdm0H+A6bRuK2HUyD3pG3xwKBgQDAhXXLcWCZMv1iHR93T7OE2vCu2mGC6Em/\nyVefUNBq/Xp8Ho7QLwoBNJoAvPuPcQviDMQ3jQT3WNIPB76NBmdAT1BjycGNCK41\nsrXTZN73mXMWyhmJDdUoKOJGTa8SbLBAG8dV5MktegDQbBr3xzLiTAsCTzjoy3XX\nWXpYZHPU7QKBgCMp/B5gN1b4CyzJtRkIyG0hp+oXS636/UkiKN8HjBixTIQ7+u49\nej3glvBQqlA9DKKiwV/I5z27UaBy5PCgG+oX0LTnc5Xs1qUmavSf4eCgjaFxT9R9\nxrzdg8CsecPbPsMjyqo+TAUERnqhPHSfiT2iz4bDZkpX0o7Zod0lRKETAoGAcTKH\nrlU9nRZ0EapaBAci4Kzy83yH9Tarlk7GbHBR+3aK/EvjYNknosnQ+zojF5Y6jHFB\nNgB+uQjKiffdvIHVV+TKucG5QjmmZQBtFJys1RyupOmz1fgCKxjO4tNuawDpKOis\nbf6Vo12m+OV3fdTsQE7B8luudIKdCUAdRbfau4kCgYEAmzvpGLSXzxzk0BSIBflN\ntq2pGTQWKTZPT0wugyMk1iuG/DLwnEU4thZD+00LSUeIMwm/J0wMx2tNVRZNyaXT\n7WPzT5hjVwpPuHRCP3QogRW+yWrN/NjX5mpclQ6gr4d7Eo92RDC4dlnxkwC2QIsr\n+CuuLjOcqhG9uCHCiyGq2kY=\n-----END PRIVATE KEY-----\n",
  "client_email": "firebase-adminsdk-fbsvc@fresh-guard-aaaf8.iam.gserviceaccount.com",
  "client_id": "114848138408631893798",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40fresh-guard-aaaf8.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}

# ----------------- Firebase Init -----------------
try:
    cred = credentials.Certificate(FIREBASE_CRED_DICT)
    firebase_app = firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL}, name="full-monitor")
    db_ref = firebase_db.reference("/", app=firebase_app)
    print("Firebase connected successfully!")
except Exception as e:
    print(f"Firebase connection error: {e}")
    db_ref = None

# ----------------- Hardware Setup -----------------
# 1. LCD Setup
lcd = None
try:
    lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2, dotsize=8)
    lcd.clear()
    lcd.write_string("Starting...")
except Exception as e:
    print(f"LCD init error: {e}")

# 2. DHT22 Setup (Pin 7 = GPIO 4)
dht_device = adafruit_dht.DHT22(board.D4, use_pulseio=False)

# 3. ADS1115 Setup
i2c = busio.I2C(board.SCL, board.SDA)
ads = None
mq135_channel = None
try:
    ads = ADS1115(i2c, address=0x48)
    mq135_channel = AnalogIn(ads, 0)
except Exception as e:
    print(f"ADS1115 init warning: {e}")

time.sleep(1.5)
if lcd:
    try:
        lcd.clear()
    except Exception:
        pass

# ----------------- Firebase Upload Function -----------------
def send_to_firebase(temp, hum, gas_val, overall_health, component_status):
    if db_ref is None:
        return "Firebase offline"
    
    payload = {
        "device_id": FIREBASE_DEVICE_ID,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "system_status": overall_health,
        "temp_c": None if temp is None else round(float(temp), 1),
        "humidity": None if hum is None else round(float(hum), 1),
        "gas_raw": None if gas_val is None else int(gas_val),
        "components": component_status
    }
    
    try:
        db_ref.child(f"pi_monitor/live/{FIREBASE_DEVICE_ID}").set(payload)
        db_ref.child(f"pi_monitor/readings/{FIREBASE_DEVICE_ID}").push(payload)
        return "Synced to Firebase"
    except Exception as err:
        return f"Upload Error: {err}"

# ----------------- Main Loop -----------------
last_firebase_upload = 0
last_gas_raw = None
dht_fail_count = 0

try:
    while True:
        temp = None
        hum = None
        comp_status = {
            "dht22": "OK",
            "mq135": "OK",
            "lcd": "OK"
        }

        # --- 1. Read DHT22 ---
        try:
            temp = dht_device.temperature
            hum = dht_device.humidity
            dht_fail_count = 0
            comp_status["dht22"] = "OK"
        except (RuntimeError, Exception):
            dht_fail_count += 1
            if dht_fail_count >= 3:
                comp_status["dht22"] = "DISCONNECTED / WIRING_ISSUE"

        time.sleep(0.05)

        # --- 2. Read MQ-135 / ADS1115 ---
        gas_raw = None
        if mq135_channel is None:
            comp_status["mq135"] = "ADS1115_INIT_FAILED"
        else:
            try:
                gas_raw = mq135_channel.value
                last_gas_raw = gas_raw
                if gas_raw == 0:
                    comp_status["mq135"] = "DISCONNECTED / ZERO_VALUE"
                else:
                    comp_status["mq135"] = "OK"
            except OSError:
                comp_status["mq135"] = "I2C_DISCONNECTED"
                gas_raw = last_gas_raw

        time.sleep(0.05)

        # --- 3. Update LCD ---
        if lcd:
            try:
                lcd.cursor_pos = (0, 0)
                t_str = f"T:{temp:.0f}C" if temp is not None else "T:ERR"
                h_str = f"H:{hum:.0f}%" if hum is not None else "H:ERR"
                lcd.write_string(f"{t_str} {h_str}".ljust(16))

                lcd.cursor_pos = (1, 0)
                g_str = f"Gas:{gas_raw}" if gas_raw is not None else "Gas:ERR"
                lcd.write_string(g_str.ljust(16))
                comp_status["lcd"] = "OK"
            except OSError:
                comp_status["lcd"] = "I2C_DISCONNECTED"
        else:
            comp_status["lcd"] = "DISCONNECTED"

        # --- 4. Evaluate System Status & Update LEDs ---
        has_issue = any(status != "OK" for status in comp_status.values())
        overall_health = "NEEDS_ATTENTION" if has_issue else "HEALTHY"
        
        # LEDs control: Healthy = Green ON, Issue = Red ON
        update_leds(overall_health)

        # --- 5. Firebase Sync (Every 15 Seconds) ---
        now = time.monotonic()
        fb_status = "Waiting..."
        if now - last_firebase_upload >= FIREBASE_INTERVAL:
            fb_status = send_to_firebase(temp, hum, gas_raw, overall_health, comp_status)
            last_firebase_upload = now

        # Terminal Print
        t_out = f"{temp:.1f} °C" if temp is not None else "FAIL"
        h_out = f"{hum:.1f} %" if hum is not None else "FAIL"
        g_out = f"{gas_raw}" if gas_raw is not None else "FAIL"
        led_str = "GREEN (OK)" if overall_health == "HEALTHY" else "RED (ERR)"
        print(f"T:{t_out:<7} | H:{h_out:<7} | Gas:{g_out:<6} | Health: {overall_health} [{led_str}] | FB: {fb_status}")

        time.sleep(2)

except KeyboardInterrupt:
    print("\nStopping monitor...")
    if lcd:
        try:
            lcd.clear()
        except Exception:
            pass
    GPIO.cleanup()
    dht_device.exit()

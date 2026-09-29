import os
import json
import time
import base64
import urllib.parse
import urllib.request
import board
import busio
import RPi.GPIO as GPIO
import adafruit_dht
from RPLCD.i2c import CharLCD
from adafruit_ads1x15.ads1115 import ADS1115
from adafruit_ads1x15.analog_in import AnalogIn
import firebase_admin
from firebase_admin import credentials, db as firebase_db

# ==================== CAMERA IMPORTS ====================
import cv2
from picamera2 import Picamera2

# ==================== PINS CONFIGURATION (AS PER CHART) ====================
GREEN_LED_PIN = 27    # Pin 13 (GPIO 27)
YELLOW_LED_PIN = 22   # Pin 15 (GPIO 22)
RED_LED_PIN = 23      # Pin 16 (GPIO 23)
BUZZER_PIN = 24       # Pin 18 (GPIO 24)
REED_PIN = 17         # Pin 11 (GPIO 17)
DHT_PIN = board.D4    # Pin 7 (GPIO 4)

# ==================== ROOM TEMPERATURE THRESHOLDS ====================
TEMP_MIN_SAFE = 18.0   # °C
TEMP_MAX_SAFE = 25.0   # °C
TEMP_MAX_WARN = 30.0   # °C (>30 = Check Food)

HUM_MIN_SAFE = 40.0    # %
HUM_MAX_SAFE = 65.0    # %
HUM_MAX_WARN = 75.0    # % (>75 = Check Food / Mold Risk)

GAS_ALERT_DELTA = 350  # Baseline se upar raw value threshold
DOOR_TIMEOUT_SEC = 10  # Seconds allowed before buzzer triggers
OFFLINE_BUFFER_FILE = "unsent_buffer.json"

# ==================== INTERVAL CONFIGURATIONS (REDUCED) ====================
THINGSPEAK_WRITE_API_KEY = "R4GNHWDCQE3B3G47"
THINGSPEAK_URL = "https://api.thingspeak.com/update.json"
THINGSPEAK_INTERVAL = 15  # Minimum 15 seconds rate limit

FIREBASE_DB_URL = "https://fresh-guard-aaaf8-default-rtdb.firebaseio.com"
FIREBASE_DEVICE_ID = "pi-01"
FIREBASE_INTERVAL = 5     # Fast interval (5 seconds)
CAMERA_ALERT_COOLDOWN = 10 # Alert snapshot cooldown (10 seconds)

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

# ==================== GPIO & HARDWARE SETUP ====================
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)

GPIO.setup(GREEN_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(YELLOW_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(RED_LED_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
GPIO.setup(REED_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

lcd = None
try:
    lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, cols=16, rows=2, dotsize=8)
    lcd.clear()
    lcd.write_string("FreshGuard Boot")
except Exception:
    pass

dht_device = adafruit_dht.DHT22(DHT_PIN, use_pulseio=False)

i2c = busio.I2C(board.SCL, board.SDA)
ads = None
mq135_channel = None
try:
    ads = ADS1115(i2c, address=0x48)
    mq135_channel = AnalogIn(ads, 0)
except Exception:
    pass

# ==================== FIREBASE SETUP ====================
db_ref = None
try:
    cred = credentials.Certificate(FIREBASE_CRED_DICT)
    firebase_app = firebase_admin.initialize_app(cred, {"databaseURL": FIREBASE_DB_URL}, name="freshguard-system")
    db_ref = firebase_db.reference("/", app=firebase_app)
    print("Connected to Firebase.")
except Exception as e:
    print(f"Firebase Offline: {e}")

# ==================== CAMERA CAPTURE FUNCTION ====================
def capture_base64_snapshot():
    """Captures a snapshot using Picamera2 and converts it to a Base64 JPEG URL string"""
    picam2 = None
    try:
        picam2 = Picamera2()
        config = picam2.create_still_configuration(main={"size": (640, 480)})
        picam2.configure(config)
        picam2.start()
        time.sleep(0.8)  # Auto-exposure warmup

        frame_rgb = picam2.capture_array()
        picam2.stop()
        picam2.close()
        picam2 = None

        frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
        success, buffer = cv2.imencode('.jpg', frame_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 65])
        if not success:
            print("[CAMERA] Encoding to JPEG failed.")
            return None

        b64_str = base64.b64encode(buffer).decode('utf-8')
        return f"data:image/jpeg;base64,{b64_str}"
    except Exception as e:
        print(f"[CAMERA ERROR] {e}")
        if picam2 is not None:
            try:
                picam2.stop()
                picam2.close()
            except Exception:
                pass
        return None

# ==================== HELPER FUNCTIONS ====================
def set_leds(has_gas_alert):
    """
    Gas detect hone par RED LED jale gi.
    Warna sab normal hone par GREEN LED jale gi.
    """
    if has_gas_alert:
        GPIO.output(RED_LED_PIN, GPIO.HIGH)
        GPIO.output(GREEN_LED_PIN, GPIO.LOW)
        GPIO.output(YELLOW_LED_PIN, GPIO.LOW)
    else:
        GPIO.output(RED_LED_PIN, GPIO.LOW)
        GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
        GPIO.output(YELLOW_LED_PIN, GPIO.LOW)

def save_to_offline_buffer(payload):
    """Saves records locally when internet connection is lost"""
    records = []
    if os.path.exists(OFFLINE_BUFFER_FILE):
        try:
            with open(OFFLINE_BUFFER_FILE, "r") as f:
                records = json.load(f)
        except Exception:
            records = []
    records.append(payload)
    with open(OFFLINE_BUFFER_FILE, "w") as f:
        json.dump(records, f)

def sync_offline_buffer():
    """Syncs unsent records when network comes back online"""
    if db_ref is None or not os.path.exists(OFFLINE_BUFFER_FILE):
        return
    try:
        with open(OFFLINE_BUFFER_FILE, "r") as f:
            records = json.load(f)
        if not records:
            return
        for r in records:
            db_ref.child(f"pi_monitor/readings/{FIREBASE_DEVICE_ID}").push(r)
        os.remove(OFFLINE_BUFFER_FILE)
        print("Offline records synced to Cloud successfully.")
    except Exception:
        pass

def send_to_thingspeak(temperature, humidity, gas_value, door_is_open, freshness_status):
    """Uploads data to ThingSpeak channel"""
    if not THINGSPEAK_WRITE_API_KEY:
        return "API Key Missing"

    stat_code = 1 if freshness_status == "Fresh/Normal" else (2 if freshness_status == "Use Soon" else 3)

    payload = {
        "api_key": THINGSPEAK_WRITE_API_KEY,
        "field1": "" if temperature is None else f"{temperature:.1f}",
        "field2": "" if humidity is None else f"{humidity:.1f}",
        "field3": "" if gas_value is None else int(gas_value),
        "field4": 1 if door_is_open else 0,
        "field5": stat_code
    }

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(THINGSPEAK_URL, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            res = response.read().decode("utf-8", errors="ignore").strip()
            if res and res != "0":
                return f"Uploaded (Entry: {res})"
            return "Rejected by ThingSpeak"
    except Exception as e:
        return f"TS Error: {e}"

def evaluate_freshness(temp, hum, gas, gas_baseline, components):
    """Freshness Decision Rule Matrix"""
    if any(s != "OK" for s in components.values()) or temp is None or hum is None:
        return "Sensor Fault", ["Sensor wiring/input fault detected!"]
    
    reasons = []
    status = "Fresh/Normal"

    # Temperature checks
    if temp > TEMP_MAX_WARN or temp < (TEMP_MIN_SAFE - 3):
        status = "Check Food"
        reasons.append("Abnormal Temperature")
    elif temp > TEMP_MAX_SAFE or temp < TEMP_MIN_SAFE:
        if status != "Check Food":
            status = "Use Soon"
        reasons.append("Temp slightly high/low")

    # Humidity checks
    if hum > HUM_MAX_WARN:
        status = "Check Food"
        reasons.append("High Humidity (Mold Risk)")
    elif hum > HUM_MAX_SAFE or hum < HUM_MIN_SAFE:
        if status != "Check Food":
            status = "Use Soon"
        reasons.append("Sub-optimal Humidity")

    # Gas checks
    if gas_baseline is not None and gas is not None:
        if (gas - gas_baseline) >= GAS_ALERT_DELTA:
            status = "Check Food"
            reasons.append("Abnormal Gas Spike")

    return status, reasons

# ==================== MAIN MONITORING LOOP ====================
print("\nStabilizing MQ-135 sensor baseline... Please wait.")
time.sleep(2)

gas_baseline = None
try:
    if mq135_channel:
        gas_baseline = mq135_channel.value
except Exception:
    pass

last_cloud_upload = 0
last_thingspeak_upload = 0
dht_fail_count = 0
last_gas_raw = 0
door_open_start_time = None
last_alert_snapshot_time = 0

try:
    while True:
        components = {"dht22": "OK", "mq135": "OK", "lcd": "OK"}
        temp, hum, gas_raw = None, None, None

        # --- 1. Read DHT22 ---
        try:
            temp = dht_device.temperature
            hum = dht_device.humidity
            dht_fail_count = 0
        except (RuntimeError, Exception):
            dht_fail_count += 1
            if dht_fail_count >= 3:
                components["dht22"] = "DISCONNECTED"

        time.sleep(0.05)

        # --- 2. Read MQ-135 ---
        if mq135_channel:
            try:
                gas_raw = mq135_channel.value
                last_gas_raw = gas_raw
                if gas_raw == 0:
                    components["mq135"] = "ZERO_VALUE"
            except OSError:
                components["mq135"] = "I2C_DISCONNECTED"
                gas_raw = last_gas_raw
        else:
            components["mq135"] = "NOT_INITIALIZED"

        time.sleep(0.05)

        if gas_baseline is None and gas_raw is not None and gas_raw > 0:
            gas_baseline = gas_raw

        # --- 3. Read Door Status (Reed Switch) ---
        door_open = GPIO.input(REED_PIN) == GPIO.HIGH
        door_alert = False
        if door_open:
            if door_open_start_time is None:
                door_open_start_time = time.monotonic()
            elif time.monotonic() - door_open_start_time >= DOOR_TIMEOUT_SEC:
                door_alert = True
        else:
            door_open_start_time = None

        # --- 4. Evaluate Status ---
        freshness_status, alerts = evaluate_freshness(temp, hum, gas_raw, gas_baseline, components)
        if door_alert:
            alerts.append("Door Left Open!")
            freshness_status = "Check Food"

        # Check gas leak/spike condition for LED
        has_gas_spike = "Abnormal Gas Spike" in alerts
        set_leds(has_gas_spike)

        # Buzzer alert (Gas spike ya open door par)
        if door_alert or has_gas_spike:
            GPIO.output(BUZZER_PIN, GPIO.HIGH)
        else:
            GPIO.output(BUZZER_PIN, GPIO.LOW)

        # --- 5. Pi Camera Snapshot (ONLY ON ABNORMAL CONDITIONS) ---
        # Normal halat mein yeh block bilkul execute nahi hoga
        now_time = time.monotonic()
        if freshness_status == "Check Food" or door_alert:
            if (now_time - last_alert_snapshot_time) >= CAMERA_ALERT_COOLDOWN:
                print("\n📸 [ALERT TRIGGERED] Abnormal conditions detected! Taking fridge snapshot...")
                img_b64 = capture_base64_snapshot()
                
                if img_b64:
                    print(f"✅ Snapshot captured! Size: {len(img_b64)} chars. Uploading to Firebase...")
                    alert_payload = {
                        "device_id": FIREBASE_DEVICE_ID,
                        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "freshness_status": freshness_status,
                        "door_status": "OPEN" if door_open else "CLOSED",
                        "temp_c": None if temp is None else round(float(temp), 1),
                        "humidity": None if hum is None else round(float(hum), 1),
                        "gas_raw": None if gas_raw is None else int(gas_raw),
                        "gas_baseline": None if gas_baseline is None else int(gas_baseline),
                        "components": components,
                        "active_alerts": alerts,
                        "image_base64": img_b64
                    }
                    
                    try:
                        if db_ref:
                            # Update live node with photo & push to history
                            db_ref.child(f"pi_monitor/live/{FIREBASE_DEVICE_ID}").update(alert_payload)
                            db_ref.child(f"pi_monitor/snapshots/{FIREBASE_DEVICE_ID}").push(alert_payload)
                            print("🔥 Alert Image successfully pushed to Firebase DB!\n")
                        else:
                            save_to_offline_buffer(alert_payload)
                            print("⚠️ Firebase offline: Image saved in local buffer.\n")
                    except Exception as err:
                        print(f"❌ Failed to upload image to Firebase: {err}\n")
                        save_to_offline_buffer(alert_payload)
                    
                    last_alert_snapshot_time = now_time
                else:
                    print("❌ Snapshot capture failed.\n")

        # --- 6. Update LCD Screen ---
        if lcd:
            try:
                lcd.cursor_pos = (0, 0)
                if components["dht22"] == "OK" and temp is not None and hum is not None:
                    g_val = gas_raw if gas_raw is not None else "--"
                    lcd.write_string(f"T:{temp:.0f}C H:{hum:.0f}% G:{g_val}".ljust(16))
                else:
                    lcd.write_string("SENSOR FAULT".ljust(16))

                lcd.cursor_pos = (1, 0)
                if door_alert:
                    lcd.write_string("CLOSE THE DOOR!".ljust(16))
                elif has_gas_spike:
                    lcd.write_string("GAS ALERT!".ljust(16))
                elif freshness_status == "Sensor Fault":
                    lcd.write_string("Data Unavail".ljust(16))
                else:
                    stat_short = "Normal" if freshness_status == "Fresh/Normal" else freshness_status
                    lcd.write_string(f"Stat: {stat_short}".ljust(16))
            except OSError:
                components["lcd"] = "I2C_DISCONNECTED"

        # --- 7. Fast Cloud Upload (Interval: 5s - SENSORS ONLY, NO IMAGE) ---
        now = time.monotonic()
        fb_status = "Waiting..."
        ts_status = "Waiting..."

        if now - last_cloud_upload >= FIREBASE_INTERVAL:
            # Normal payload mein image_base64 include nahi ki gayi
            payload = {
                "device_id": FIREBASE_DEVICE_ID,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "freshness_status": freshness_status,
                "door_status": "OPEN" if door_open else "CLOSED",
                "temp_c": None if temp is None else round(float(temp), 1),
                "humidity": None if hum is None else round(float(hum), 1),
                "gas_raw": None if gas_raw is None else int(gas_raw),
                "gas_baseline": None if gas_baseline is None else int(gas_baseline),
                "components": components,
                "active_alerts": alerts
            }

            try:
                if db_ref:
                    # .update() use kiya gaya hai taake latest image_base64 delete na ho
                    db_ref.child(f"pi_monitor/live/{FIREBASE_DEVICE_ID}").update(payload)
                    db_ref.child(f"pi_monitor/readings/{FIREBASE_DEVICE_ID}").push(payload)
                    sync_offline_buffer()
                    fb_status = "Synced"
                else:
                    save_to_offline_buffer(payload)
                    fb_status = "Buffered Locally"
            except Exception:
                save_to_offline_buffer(payload)
                fb_status = "Buffered Locally"

            last_cloud_upload = now

        # ThingSpeak upload (15s rate limit)
        if now - last_thingspeak_upload >= THINGSPEAK_INTERVAL:
            ts_status = send_to_thingspeak(temp, hum, gas_raw, door_open, freshness_status)
            last_thingspeak_upload = now

        # Terminal Log
        t_str = f"{temp:.1f}C" if temp is not None else "--"
        h_str = f"{hum:.1f}%" if hum is not None else "--"
        print(f"[{time.strftime('%H:%M:%S')}] T:{t_str} | H:{h_str} | Gas:{gas_raw} | Door:{'OPEN' if door_open else 'CLOSED'} | Status:{freshness_status} | FB:{fb_status} | TS:{ts_status}")

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping FreshGuard Monitor...")
    if lcd:
        try:
            lcd.clear()
        except Exception:
            pass
    GPIO.output(BUZZER_PIN, GPIO.LOW)
    GPIO.output(GREEN_LED_PIN, GPIO.LOW)
    GPIO.output(YELLOW_LED_PIN, GPIO.LOW)
    GPIO.output(RED_LED_PIN, GPIO.LOW)
    GPIO.cleanup()
    dht_device.exit()
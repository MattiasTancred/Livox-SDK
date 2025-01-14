import zmq
import lgpio
import subprocess
import time
import os
import signal
import sys
import json

# GPIO Pins
BUTTON_PIN = 23  # GPIO23 (Physical Pin 16)
PHOTO_LED_PIN = 27  # GPIO27 (Physical Pin 13)
GCP_BUTTON_PIN = 24  # GPIO24
GCP_LED_PIN = 20  # GPIO20

# Log File
LOG_FILE = "/home/slam/Pictures/Theta/photo_log.txt"
CURRENT_FOLDER_FILE = "/tmp/current_output_folder.txt"

# Kill Processes Using GPIO or USB
def kill_gpio_users():
    try:
        result = subprocess.run(["sudo", "fuser", "/dev/gpiochip*"], capture_output=True, text=True)
        pids = [pid for pid in result.stdout.split() if pid.isdigit()]
        for pid in pids:
            subprocess.run(["sudo", "kill", "-9", pid])
    except Exception as e:
        print(f"[ERROR] Error killing GPIO users: {e}")

def kill_usb_locks():
    try:
        result = subprocess.run(["sudo", "fuser", "/dev/bus/usb/002/003"], capture_output=True, text=True)
        pids = [pid for pid in result.stdout.split() if pid.isdigit()]
        for pid in pids:
            subprocess.run(["sudo", "kill", "-9", pid])
    except Exception as e:
        print(f"[ERROR] Error killing USB locks: {e}")

# GPIO Setup and Release Functions
def release_gpio(chip_handle):
    try:
        lgpio.gpiochip_close(chip_handle)
    except lgpio.error:
        pass

def setup_gpio(chip_handle):
    lgpio.gpio_claim_input(chip_handle, BUTTON_PIN, lgpio.SET_PULL_UP)
    lgpio.gpio_claim_output(chip_handle, PHOTO_LED_PIN, 0)
    lgpio.gpio_claim_input(chip_handle, GCP_BUTTON_PIN, lgpio.SET_PULL_UP)
    lgpio.gpio_claim_output(chip_handle, GCP_LED_PIN, 0)

def setup_gpio_with_retry(chip_handle, retries=3):
    for attempt in range(retries):
        try:
            setup_gpio(chip_handle)
            return
        except lgpio.error as e:
            print(f"[ERROR] GPIO setup attempt {attempt + 1} failed: {e}")
            time.sleep(1)
    raise RuntimeError("[FATAL] Failed to set up GPIO after multiple attempts")

def blink_led(chip_handle, pin, times, interval):
    for _ in range(times):
        lgpio.gpio_write(chip_handle, pin, 1)
        time.sleep(interval)
        lgpio.gpio_write(chip_handle, pin, 0)
        time.sleep(interval)
    print("[DEBUG] Blink sequence complete.")

def turn_led_on(chip_handle, pin):
    lgpio.gpio_write(chip_handle, pin, 1)

def turn_led_off(chip_handle, pin):
    lgpio.gpio_write(chip_handle, pin, 0)

def get_photo_output_directory():
    try:
        with open(CURRENT_FOLDER_FILE, "r") as f:
            base_dir = f.read().strip()
        if not base_dir:
            print("[ERROR] Empty base directory path")
            return None
        photo_output_dir = os.path.join(base_dir, "360")
        os.makedirs(photo_output_dir, exist_ok=True)
        return photo_output_dir
    except Exception as e:
        print(f"[ERROR] Error retrieving photo directory: {e}")
        return None

# Add new function to get GCP directory
def get_gcp_directory():
    try:
        with open(CURRENT_FOLDER_FILE, "r") as f:
            base_dir = f.read().strip()
        if not base_dir:
            print("[ERROR] Empty base directory path")
            return None
        gcp_dir = os.path.join(base_dir, "GCP")
        os.makedirs(gcp_dir, exist_ok=True)
        return gcp_dir
    except Exception as e:
        print(f"[ERROR] Error retrieving GCP directory: {e}")
        return None

def capture_photo(photo_output_dir):
    existing_files = [f for f in os.listdir(photo_output_dir) if f.endswith('.jpg')]
    next_number = len(existing_files) + 1
    image_path = os.path.join(photo_output_dir, f"{next_number}.jpg")
    
    try:
        lidar_timestamp = extract_latest_timestamp_from_zmq()
        
        result = subprocess.run(
            ["gphoto2", "--capture-image-and-download", "--force-overwrite", 
             "--filename", image_path],
            check=True,
            capture_output=True,
            text=True
        )
            
        if os.path.exists(image_path):
            save_image_with_timestamp(photo_output_dir, os.path.basename(image_path), lidar_timestamp)
            return True
        else:
            print(f"[ERROR] Image file was not created at: {image_path}")
            return False
            
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to capture photo: {e}")
        return False

def save_gcp_timestamp(photo_output_dir, lidar_timestamp):
    try:
        gcp_dir = get_gcp_directory()
        if not gcp_dir:
            print("[ERROR] Failed to create GCP directory")
            return False
            
        gcp_file = os.path.join(gcp_dir, "gcp_timestamps.txt")
        # Count existing GCP points
        if os.path.exists(gcp_file):
            with open(gcp_file, "r") as f:
                gcp_count = len(f.readlines()) + 1
        else:
            gcp_count = 1
            
        # Append new GCP timestamp
        with open(gcp_file, "a") as f:
            f.write(f"GCP{gcp_count} {lidar_timestamp}\n")
        print(f"[DEBUG] Saved GCP{gcp_count} with timestamp: {lidar_timestamp}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save GCP timestamp: {e}")
        return False

def extract_latest_timestamp_from_zmq():
    context = None
    socket = None
    try:
        context = zmq.Context()
        socket = context.socket(zmq.SUB)
        socket.connect("tcp://127.0.0.1:5556")
        socket.setsockopt_string(zmq.SUBSCRIBE, "")
        socket.setsockopt(zmq.RCVTIMEO, 5000)  # 5 second timeout
        message = socket.recv_string()
        data = json.loads(message)
        return data.get("time", "NO_TIMESTAMP")
    except zmq.ZMQError as e:
        print(f"[ERROR] ZMQ error: {e}")
        return "NO_TIMESTAMP"
    except (json.JSONDecodeError, KeyError) as e:
        print(f"[ERROR] Data parsing error: {e}")
        return "NO_TIMESTAMP"
    finally:
        if socket:
            socket.close()
        if context:
            context.term()

def take_dummy_image_with_blink(chip_handle, led_pin):
    try:
        print("[DEBUG] Attempting to capture dummy image...")
        turn_led_on(chip_handle, led_pin)
        
        result = subprocess.run(
            ["gphoto2", "--capture-image-and-download", "--force-overwrite", 
             "--filename", "/tmp/dummy.jpg", "--debug", "--debug-logfile=/tmp/gphoto2_dummy.log"],
            check=True,
            capture_output=True,
            text=True
        )

        for _ in range(25):
            turn_led_off(chip_handle, led_pin)
            time.sleep(0.2)
            turn_led_on(chip_handle, led_pin)
            time.sleep(0.2)
        
        turn_led_off(chip_handle, led_pin)
            
        if os.path.exists("/tmp/dummy.jpg"):
            print("[DEBUG] Dummy image captured successfully")
            os.remove("/tmp/dummy.jpg")
            lidar_timestamp = extract_latest_timestamp_from_zmq()
            print(f"[DEBUG] Dummy image timestamp: {lidar_timestamp}")
            return True
        else:
            print("[ERROR] Dummy image file was not created")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to capture dummy image: {e}")
        print(f"[ERROR] Exception type: {type(e)}")
        if isinstance(e, subprocess.CalledProcessError):
            print(f"[ERROR] Command output: {e.output}")
        turn_led_off(chip_handle, led_pin)
        return False

def save_image_with_timestamp(photo_output_dir, image_name, lidar_timestamp):
    try:
        timestamps_file = os.path.join(photo_output_dir, "timestamps.txt")
        with open(timestamps_file, "a") as f:
            f.write(f"{image_name}, {lidar_timestamp}\n")
        print(f"[DEBUG] Saved: {image_name}, {lidar_timestamp}")
    except Exception as e:
        print(f"[ERROR] Failed to save to timestamps.txt: {e}")

def handle_signal(signum, frame, chip_handle):
    print("[INFO] Shutting down gracefully...")
    if chip_handle is not None:
        release_gpio(chip_handle)
    sys.exit(0)

def fancy_blink_pattern(chip_handle, pin):
    """Creates an interesting LED pattern during initialization"""
    # Quick triple-flash to start
    for _ in range(3):
        lgpio.gpio_write(chip_handle, pin, 1)
        time.sleep(0.1)
        lgpio.gpio_write(chip_handle, pin, 0)
        time.sleep(0.1)
    
    time.sleep(0.5)  # Pause
    
    # Slow breathing effect
    for _ in range(3):
        # Fade in
        lgpio.gpio_write(chip_handle, pin, 1)
        time.sleep(0.8)
        lgpio.gpio_write(chip_handle, pin, 0)
        time.sleep(0.8)
    
    # Quick excitement pattern
    for _ in range(6):
        lgpio.gpio_write(chip_handle, pin, 1)
        time.sleep(0.2)
        lgpio.gpio_write(chip_handle, pin, 0)
        time.sleep(0.2)
    
    time.sleep(0.5)  # Pause
    
    # Final countdown - slower blinks
    for i in range(5):
        lgpio.gpio_write(chip_handle, pin, 1)
        time.sleep(1)
        lgpio.gpio_write(chip_handle, pin, 0)
        time.sleep(1)

def main():
    chip_handle = None
    first_button_press = True
    last_capture_time = 0
    last_gcp_time = 0
    MIN_CAPTURE_INTERVAL = 2

    try:
        signal.signal(signal.SIGINT, lambda s, f: handle_signal(s, f, chip_handle))
        signal.signal(signal.SIGTERM, lambda s, f: handle_signal(s, f, chip_handle))

        kill_gpio_users()
        kill_usb_locks()

        chip_handle = lgpio.gpiochip_open(0)
        setup_gpio_with_retry(chip_handle)
        print("[INFO] GPIO setup complete, ready for operation")

        while True:
            current_time = time.time()
            
            # Photo button logic
            if lgpio.gpio_read(chip_handle, BUTTON_PIN) == 0:
                if first_button_press:
                    print("[INFO] First button press detected")
                    if take_dummy_image_with_blink(chip_handle, PHOTO_LED_PIN):
                        first_button_press = False
                        last_capture_time = current_time
                        print("[DEBUG] Initialization complete")
                    else:
                        print("[ERROR] Dummy image capture failed")
                
                elif current_time - last_capture_time >= MIN_CAPTURE_INTERVAL:
                    print("[INFO] Button press detected - capturing photo")
                    turn_led_on(chip_handle, PHOTO_LED_PIN)
                    photo_output_dir = get_photo_output_directory()
                    
                    if photo_output_dir:
                        success = capture_photo(photo_output_dir)
                        if success:
                            last_capture_time = current_time
                    else:
                        print("[ERROR] Failed to get photo output directory")
                    
                    turn_led_off(chip_handle, PHOTO_LED_PIN)
                time.sleep(0.5)  # Debounce delay
                
            # GCP button logic
            elif lgpio.gpio_read(chip_handle, GCP_BUTTON_PIN) == 0:
                if current_time - last_gcp_time >= MIN_CAPTURE_INTERVAL:
                    print("[INFO] GCP button press detected")
                    turn_led_on(chip_handle, GCP_LED_PIN)
                    
                    photo_output_dir = get_photo_output_directory()
                    if photo_output_dir:
                        lidar_timestamp = extract_latest_timestamp_from_zmq()
                        if save_gcp_timestamp(photo_output_dir, lidar_timestamp):
                            last_gcp_time = current_time
                    else:
                        print("[ERROR] Failed to get output directory for GCP")
                    
                    turn_led_off(chip_handle, GCP_LED_PIN)
                time.sleep(0.5)  # Debounce delay
                
            time.sleep(0.1)

    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
    finally:
        if chip_handle is not None:
            release_gpio(chip_handle)
            print("[INFO] GPIO resources released")

if __name__ == "__main__":
    main()

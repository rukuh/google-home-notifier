import os
import re
import html
import time
import socket
import logging
import hashlib
import atexit
from flask import Flask, request, jsonify, send_from_directory
from gtts import gTTS
import pychromecast
import zeroconf

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Initialize a global, persistent Zeroconf instance to share across pychromecast calls
try:
    ZCONF = zeroconf.Zeroconf()
except Exception as e:
    logger.error(f"Failed to initialize global Zeroconf: {e}")
    ZCONF = None

@atexit.register
def cleanup_zeroconf():
    if ZCONF:
        try:
            ZCONF.close()
            logger.info("Closed global Zeroconf instance.")
        except Exception as e:
            logger.error(f"Error closing global Zeroconf: {e}")

app = Flask(__name__)

# Config
PORT = int(os.environ.get("PORT", 8091))
CHROMECAST_NAME = os.environ.get("CHROMECAST_NAME")
CHROMECAST_IP = os.environ.get("CHROMECAST_IP")
SERVER_IP = os.environ.get("SERVER_IP")
NOTIFIER_API_KEY = os.environ.get("NOTIFIER_API_KEY")
REPEAT_MESSAGE = os.environ.get("REPEAT_MESSAGE", "true").lower() in ("true", "1", "yes")
INTRO_PREFIX = os.environ.get("INTRO_PREFIX", "Attention: ")
TTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

if not os.path.exists(TTS_DIR):
    os.makedirs(TTS_DIR)

def get_local_ip():
    if SERVER_IP:
        return SERVER_IP
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip

def get_chromecast_device(speaker_name=None, speaker_ip=None):
    """
    Finds and connects to a Chromecast device.
    """
    # 1. Connect by IP if provided
    ip_to_use = speaker_ip or CHROMECAST_IP
    name_to_use = speaker_name or CHROMECAST_NAME
    if ip_to_use:
        logger.info(f"Connecting to Chromecast at IP: {ip_to_use} (target name: {name_to_use})")
        chromecasts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[name_to_use] if name_to_use else None,
            known_hosts=[ip_to_use],
            zeroconf_instance=ZCONF
        )
        if chromecasts:
            cast = chromecasts[0]
            cast.wait()
            browser.stop_discovery()
            return cast
        logger.warning(f"Could not connect to Chromecast at IP {ip_to_use}, falling back to name/discovery")

    # 2. Discover by name
    name_to_use = speaker_name or CHROMECAST_NAME
    if name_to_use:
        logger.info(f"Discovering Chromecast with name: {name_to_use}")
        chromecasts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[name_to_use],
            zeroconf_instance=ZCONF
        )
        if chromecasts:
            cast = chromecasts[0]
            cast.wait()
            browser.stop_discovery()
            return cast
        logger.warning(f"Chromecast '{name_to_use}' not found, discovering all...")

    # 3. Fallback to discover all and grab the first one
    logger.info("Discovering all Chromecasts on network...")
    
    class SimpleListener(pychromecast.discovery.AbstractCastListener):
        def add_cast(self, uuid, service):
            pass
        def remove_cast(self, uuid, service, cast_info):
            pass
        def update_cast(self, uuid, service):
            pass

    browser = pychromecast.CastBrowser(SimpleListener(), ZCONF)
    browser.start_discovery()
    # Wait for discovery to run
    time.sleep(5.0)
    browser.stop_discovery()

    if browser.devices:
        uuid = list(browser.devices.keys())[0]
        cast_info = browser.devices[uuid]
        logger.info(f"Found Chromecast '{cast_info.friendly_name}'. Connecting...")
        chromecasts, browser2 = pychromecast.get_listed_chromecasts(
            uuids=[uuid],
            zeroconf_instance=ZCONF
        )
        if chromecasts:
            cast = chromecasts[0]
            cast.wait()
            browser2.stop_discovery()
            return cast
        
    return None


def clean_old_files():
    """Clean up files in TTS_DIR older than 1 hour."""
    now = time.time()
    for f in os.listdir(TTS_DIR):
        file_path = os.path.join(TTS_DIR, f)
        if os.path.isfile(file_path):
            if os.stat(file_path).st_mtime < now - 3600:
                try:
                    os.remove(file_path)
                    logger.info(f"Deleted old TTS file: {f}")
                except Exception as e:
                    logger.error(f"Error deleting old TTS file {f}: {e}")

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(TTS_DIR, filename)

def clean_html(text):
    if not text:
        return ""
    # Convert markdown links [text](http...) -> text
    clean = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # Remove HTML tags (including <a href="..."></a>)
    clean = re.sub(r'<[^>]*>', ' ', clean)
    # Remove any standalone/leftover URLs
    clean = re.sub(r'https?://\S+', '', clean)
    # Decode HTML entities (e.g. &nbsp; -> space)
    clean = html.unescape(clean)
    # Normalize whitespace
    clean = ' '.join(clean.split())
    # Remove trailing label if it pointed to a stripped URL (e.g. "Link:")
    clean = re.sub(r'\s*(?:link|url):\s*$', '', clean, flags=re.IGNORECASE)
    return clean.strip()

@app.route('/broadcast', methods=['POST'])
def broadcast():
    logger.info(f"Incoming POST to /broadcast")
    logger.info(f"HEADERS: {dict(request.headers)}")
    logger.info(f"ARGS: {dict(request.args)}")
    logger.info(f"FORM: {dict(request.form)}")
    logger.info(f"JSON: {request.get_json(silent=True)}")
    logger.info(f"RAW DATA: {request.data[:500]}") # limit logging size

    if NOTIFIER_API_KEY:
        auth_header = request.headers.get("Authorization")
        if not auth_header or auth_header != f"Bearer {NOTIFIER_API_KEY}":
            logger.warning("Unauthorized request to /broadcast")
            return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    message = (
        data.get("message") or 
        data.get("body") or 
        data.get("title") or 
        request.form.get("message") or 
        request.form.get("body") or 
        request.form.get("title")
    )

    if not message and request.data:
        try:
            # Check if raw data is a JSON string
            import json
            raw_json = json.loads(request.data)
            message = raw_json.get("message") or raw_json.get("body") or raw_json.get("title")
        except Exception:
            # Otherwise, treat raw data as plain text/HTML
            message = request.data.decode('utf-8', errors='ignore')

    if not message:
        return jsonify({"error": "Missing message content in request body."}), 400

    # Clean HTML tags and decode entities for cleaner TTS speech
    message = clean_html(message)
    logger.info(f"Cleaned message to read: '{message}'")

    repeat_param = request.args.get("repeat")
    if repeat_param is None:
        repeat_param = data.get("repeat")
    if repeat_param is not None:
        should_repeat = str(repeat_param).lower() in ("true", "1", "yes")
    else:
        should_repeat = REPEAT_MESSAGE

    prefix = request.args.get("prefix")
    if prefix is None:
        prefix = data.get("prefix", INTRO_PREFIX)

    clean_msg = message.rstrip('. ')
    if prefix and not clean_msg.lower().startswith(prefix.strip().lower()):
        first_pass = f"{prefix.strip()} {clean_msg}"
    else:
        first_pass = clean_msg

    if should_repeat:
        speech_text = f"{first_pass}. ... Repeating: {clean_msg}."
    else:
        speech_text = f"{first_pass}."

    speaker_name = data.get("speaker") or request.form.get("speaker")
    speaker_ip = data.get("speaker_ip") or request.form.get("speaker_ip")
    lang = data.get("lang", "en")

    logger.info(f"Synthesizing speech text: '{speech_text}' (lang: {lang})")

    # Clean old files to prevent disk usage from growing
    clean_old_files()

    try:
        # Generate hash for unique filename
        text_hash = hashlib.md5(f"{speech_text}-{lang}".encode('utf-8')).hexdigest()
        filename = f"tts_{text_hash}.mp3"
        filepath = os.path.join(TTS_DIR, filename)

        # Generate text-to-speech file if it doesn't exist
        if not os.path.exists(filepath):
            logger.info(f"Generating new TTS file: {filename}")
            tts = gTTS(text=speech_text, lang=lang)
            tts.save(filepath)
        else:
            logger.info(f"Using cached TTS file: {filename}")

        cast = None
        try:
            # Find Chromecast
            cast = get_chromecast_device(speaker_name, speaker_ip)
            if not cast:
                return jsonify({"error": "No Google Home/Chromecast device found on network."}), 500

            # Build media URL
            local_ip = get_local_ip()
            media_url = f"http://{local_ip}:{PORT}/static/{filename}"
            logger.info(f"Casting to '{cast.name}' via {media_url}")

            # Play media on Chromecast
            cast.media_controller.play_media(media_url, "audio/mp3")
            cast.media_controller.block_until_active()

            return jsonify({
                "status": "success",
                "message": f"Broadcasted to '{cast.name}' successfully.",
                "device": cast.name,
                "media_url": media_url
            }), 200
        finally:
            if cast:
                try:
                    cast.disconnect()
                    logger.info(f"Disconnected from Chromecast: {cast.name}")
                except Exception as ex:
                    logger.error(f"Error disconnecting from Chromecast: {ex}")

    except Exception as e:
        logger.exception("Failed to broadcast message")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    logger.info(f"Starting Google Home Notifier on port {PORT}")
    app.run(host='0.0.0.0', port=PORT)

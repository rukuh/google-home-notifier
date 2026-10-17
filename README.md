# Google Home Notifier Service Integration

We have created and deployed a lightweight **Google Home Notifier** microservice that allows **changedetection.io** (or any webhook sender) to broadcast text-to-speech notifications to your Google Home speakers.

---

## File Structure

The service is self-contained and located in the repository:
*   [app.py](app.py): The main Flask-based Python application that uses `pychromecast` to discover Google Home devices and `gTTS` to generate speech MP3s.
*   [requirements.txt](requirements.txt): Lists Python dependencies (`Flask`, `gTTS`, `PyChromecast`, and `gunicorn`).
*   [Dockerfile](Dockerfile): The container build instruction.

---

## Docker Integration

The service is integrated directly into Docker Compose:

```yaml
  google-home-notifier:
    build: Workspace/google-home-notifier
    container_name: google-home-notifier
    restart: unless-stopped
    environment:
      CHROMECAST_IP: ${CHROMECAST_IP}
      CHROMECAST_NAME: ${CHROMECAST_NAME}
      REPEAT_MESSAGE: "true"
      PORT: 8091
    network_mode: host
```

> [!NOTE]
> The service runs on **host network mode** (`network_mode: host`) so it can discover Google Home/Chromecast speakers on your local network using mDNS (multicast DNS). It binds directly to port `8091` on the host.

Configuration environment variables:
*   `CHROMECAST_IP`: If specified, connects directly to the given IP address (bypassing discovery for speed and reliability).
*   `CHROMECAST_NAME`: The name of the speaker or group (e.g., "Home group", "Living Room Speaker") to target.
*   `REPEAT_MESSAGE`: Set to `"true"` (default) to repeat announcements with an attention prefix and pause.
*   `NOTIFIER_API_KEY`: Optional Bearer token for authenticating requests.

---

## API Reference

The service exposes a POST route `/broadcast` at `http://<SERVER_IP>:8091/broadcast`.

### Request Body (JSON)
The endpoint accepts standard JSON payloads:
*   `message` (or `body` / `title`): The text content you want the speaker to read.
*   `repeat` (optional, default `true`): Whether to repeat the message with a brief pause (`"Attention: <msg>. ... Repeating: <msg>."`).
*   `prefix` (optional, default `"Attention: "`): Prefix spoken before the first announcement to act as an audio wake-up buffer.
*   `speaker` (optional): Override target speaker name.
*   `speaker_ip` (optional): Override target speaker IP.
*   `lang` (optional, default `"en"`): TTS language code.

Example `curl` payload:
```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"message": "Hello from changedetection!"}' \
  http://<SERVER_IP>:8091/broadcast
```

---

## Configuring changedetection.io

To trigger broadcast notifications from changedetection.io:

1.  Open your **changedetection.io** web dashboard.
2.  Go to **Settings** (for global alerts) or click **Edit** on a specific watch (for individual watch alerts).
3.  Go to the **Notifications** tab.
4.  In the **Notification URL** field, add the Apprise webhook endpoint:
    ```text
    post://<SERVER_IP>:8091/broadcast?+content-type=application/json
    ```
    *(If `NOTIFIER_API_KEY` is configured, append `&+Authorization=Bearer%20<YOUR_KEY>`)*
5.  In the **Notification Body** field, define the content:
    ```html
    <a href="{{ watch_url }}">{{ watch_title }}</a>: {{ llm_summary if llm_summary else diff_added }}
    ```
6.  Click **Save** and then click **Send test notification** to verify the audio plays on your Google Home.

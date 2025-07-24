import network
import socket
import machine
import utime
import time
import os
from machine import ADC, Pin

CONFIG_FILE = "wifi_config.txt"
AP_SSID = "PicoSetup"
AP_PASSWORD = "12345678"

soil_sensor = ADC(Pin(26))
relay = Pin(16, Pin.OUT, value=1)
conversion_factor = 100/(65535)

time_trigger = None
sensor_trigger = False

def display_time():
    current_time = time.localtime()
    print(f"Current time: {current_time[3]:02d}:{current_time[4]:02d}:{current_time[5]:02d}")

def url_decode(s):
    res = ""
    i = 0
    while i < len(s):
        if s[i] == '%' and i + 2 < len(s):
            try:
                hex_val = s[i+1:i+3]
                res += chr(int(hex_val, 16))
                i += 3
            except:
                res += s[i]
                i += 1
        elif s[i] == '+':
            res += ' '
            i += 1
        else:
            res += s[i]
            i += 1
    return res

def save_credentials(ssid, password):
    with open(CONFIG_FILE, "w") as f:
        f.write(f"{ssid}\n{password}")

def load_credentials():
    try:
        with open(CONFIG_FILE, "r") as f:
            lines = f.read().splitlines()
            if len(lines) >= 2:
                return lines[0], lines[1]
    except:
        pass
    return None, None

def connect_to_wifi(ssid, password):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    utime.sleep(1)
    wlan.active(True)
    utime.sleep(1)
    wlan.connect(ssid, password)
    print(f"Connecting to {ssid}...")

    for i in range(15):
        if wlan.isconnected():
            print("Connected! IP:", wlan.ifconfig()[0])
            return wlan
        print(f"Waiting for connection... {i+1}/15")
        utime.sleep(1)

    print("Failed to connect. Resetting WLAN and retrying...")
    wlan.active(False)
    utime.sleep(1)
    wlan.active(True)
    wlan.connect(ssid, password)
    for i in range(15):
        if wlan.isconnected():
            print("Connected! IP:", wlan.ifconfig()[0])
            return wlan
        utime.sleep(1)

    print("Final connection attempt failed.")
    return None

def start_ap_mode():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid=AP_SSID, password=AP_PASSWORD)
    print("AP Mode active. Connect to:", AP_SSID)

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    print("Listening on", ap.ifconfig())

    html_form = """\
HTTP/1.1 200 OK
Content-Type: text/html

<!DOCTYPE html>
<html>
  <head>
    <title>Wi-Fi Setup</title>
    <script>
      function togglePassword() {
        var pwd = document.getElementById("password");
        if (pwd.type === "password") {
          pwd.type = "text";
        } else {
          pwd.type = "password";
        }
      }
    </script>
  </head>
  <body>
    <h2>Enter Wi-Fi Credentials</h2>
    <form action="/save" method="get">
      SSID: <input name="ssid" type="text" /><br/>
      Password: <input id="password" name="password" type="password" /><br/>
      <input type="checkbox" id="showPwd" onclick="togglePassword()" />
      <label for="showPwd">Show Password</label><br/><br/>
      <input type="submit" value="Save & Connect" />
    </form>
    <br/>
    <form action="/forget" method="get">
      <input type="submit" value="Forget Wi-Fi Credentials" />
    </form>
  </body>
</html>
"""

    while True:
        client, addr = s.accept()
        request = client.recv(1024).decode()
        print("Request:", request)

        if "GET /?time=" in request:
            try:
                time_param = request.split("GET /?time=")[1].split(" ")[0]
                global time_trigger
                time_trigger = url_decode(time_param)
                print("Time trigger set to:", time_trigger)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nTime trigger received.")
            except:
                client.send("HTTP/1.1 400 Bad Request\r\n\r\nCould not parse time.")
            client.close()

        elif "GET /?sensor=" in request:
            global sensor_trigger
            sensor_trigger = True
            print("Sensor trigger received.")
            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nSensor trigger received.")
            client.close()

        elif "GET /save?" in request:
            try:
                params = request.split("GET /save?")[1].split(" ")[0]
                pairs = params.split("&")
                query = {}
                for p in pairs:
                    if "=" in p:
                        k, v = p.split("=", 1)
                        query[k] = url_decode(v)
                ssid = query.get("ssid", "")
                password = query.get("password", "")
                save_credentials(ssid, password)
                print("Decoded SSID:", ssid)
                print("Decoded Password:", password)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h3>Saved! Rebooting...</h3>")
                client.close()
                utime.sleep(2)
                machine.reset()
            except:
                client.send("HTTP/1.1 400 Bad Request\r\n\r\nFailed to parse form")
                client.close()

        elif "GET /forget" in request:
            try:
                os.remove(CONFIG_FILE)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h3>Wi-Fi credentials forgotten. Rebooting...</h3>")
                client.close()
                utime.sleep(2)
                machine.reset()
            except:
                client.send("HTTP/1.1 500 Internal Server Error\r\n\r\nFailed to forget credentials")
                client.close()

        else:
            client.send(html_form)
            client.close()

def handle_sta_requests(wlan):
    global time_trigger, sensor_trigger

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    print("Listening for commands on", wlan.ifconfig())

    while True:
        client, addr = s.accept()
        print("Client connected from", addr)
        request = client.recv(1024).decode()
        print("Request:", request)

        if "GET /?time=" in request:
            try:
                time_param = request.split("GET /?time=")[1].split(" ")[0]
                time_trigger = url_decode(time_param)
                print("Time trigger set to:", time_trigger)
                client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nTime trigger received.")
            except:
                client.send("HTTP/1.1 400 Bad Request\r\n\r\nCould not parse time.")
            client.close()

        elif "GET /?sensor=" in request:
            sensor_trigger = True
            print("Sensor trigger received.")
            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nSensor trigger received.")
            client.close()

        elif "GET /ping" in request:
            client.send("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nPico is online.")
            client.close()

        else:
            client.send("HTTP/1.1 404 Not Found\r\n\r\nUnknown request.")
            client.close()

def get_soil_moisture():
    global time_trigger, sensor_trigger
    relay.value(1)
    while True:
        moisture = 130 - (soil_sensor.read_u16() * conversion_factor)
        print("Moisture: ", round(moisture,1), "% - ", utime.localtime())
        display_time()

        # Trigger relay based on time
        current_time_str = f"{utime.localtime()[3]}:{utime.localtime()[4]}"
        if time_trigger == current_time_str:
            print("Time matched! Activating relay.")
            relay.value(0)
            utime.sleep(10)
            relay.value(1)
            time_trigger = None  # Reset after triggered

        # Trigger relay based on sensor flag and moisture level
        while sensor_trigger:
            moisture = 130 - (soil_sensor.read_u16() * conversion_factor)
            print("Moisture: ", round(moisture,1), "% - ", utime.localtime())
            if moisture < 70:
                print("Sensor trigger and low moisture! Activating relay.")
                
                relay.value(0)
                utime.sleep(3)
                relay.value(1)
                utime.sleep(10)
            utime.sleep(1)
            

        utime.sleep(1)

def main():
    relay.value(1)
    ssid, password = load_credentials()
    wlan = None
    if ssid:
        wlan = connect_to_wifi(ssid, password)
    if wlan and wlan.isconnected():
        print("Wi-Fi connected. Starting command server...")
        # In a real case, you might want threading to run both:
        # Here we run handle_sta_requests in parallel and run soil moisture logic too.
        import _thread
        _thread.start_new_thread(handle_sta_requests, (wlan,))
        get_soil_moisture()
    else:
        print("Could not connect. Starting AP mode...")
        start_ap_mode()

if __name__ == "__main__":
    main()


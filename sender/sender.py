import subprocess
import re

import socket
import sys
import socket


def get_bandwidth_mbit(server_ip):
    try:
        # iperf3 client.
        result = subprocess.run(['iperf3', '-c', server_ip, '-u', '-t', '-b', '800M'], capture_output=True, text=True)
        
        # Look for row "receiver"
        for line in result.stdout.splitlines():
            if 'receiver' in line:
                # Ex: "[ ID]   Interval          Transfer     Bitrate         Retr"
                match = re.search(r'(\d+(?:\.\d+)?)\s+Mbits/sec', line)
                if match:
                    bandwidth = float(match.group(1))
                    print(f"Current bandwidth: {bandwidth:.2f} Mbit/s")
                    return bandwidth
        print("ERROR: Can not retreive bandwidth information.")
        sys.exit(1)
    except Exception as e:
        print(f"Error measuring bandwidth: {e}")
        print("Program terminated since resolution cannot be determined.")
        sys.exit(1)


def determine_resolution_from_bandwidth(bandwidth):
    if bandwidth <= 160:
        return 480, 270, '270p', 'Bandwidth too low to send video as 1080p or 540p.'  # 4x downsampling
    elif bandwidth <= 630:
        return 960, 540, '540p', 'Bandwidth too low to send video as 1080p.'  # 2x downsampling
    else:
        return 1920, 1080, '1080p', 'Bandwidth good enough, no downscaling needed.'  # Original
        
        
def send_resolution_over_tcp(receiver_ip, port, width, height, bandwidth):

    if bandwidth <= 160:
        scale = 4
    elif bandwidth <= 630:
        scale = 2
    else:
        scale = 1

    scaled = scale != 1
    metadata = f"width={width};height={height};scaled={str(scaled).lower()};scale={scale}"

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.connect((receiver_ip, port))
            print(f"Connected to receiver at {receiver_ip}:{port}, sending resolution...")
            sock.sendall(metadata.encode('utf-8'))
            print(f"Sent: {metadata}")
    except Exception as e:
        print(f"Program terminated. Could not send resolution metadata: {e}")
        print("Receiver cannot create pipeline unless it receives metadata about resolution.")
        print("Please check ip address, if receiver is running and connected to network, or network configuration and try again.")
        sys.exit(1)



def run_gstreamer_pipeline(width, height, resolution_label, info):
    gstreamer_command = [
        'gst-launch-1.0', 'filesrc', 'location=BasketballDrive2_y_only_ori.yuv',
        '!', 'rawvideoparse', 'format=i420', 'width=1920', 'height=1080', 'framerate=25/1',
        '!', 'videoscale',
        '!', f'video/x-raw,width={width},height={height}',
        '!', 'filesink', f'location=downscaled_{resolution_label}.yuv'
    ]
    print(f"{info}")
    print(f"Videofile downscaled to {width}x{height} -> downscaled_{resolution_label}.yuv")
    subprocess.run(gstreamer_command)


def stream_downscaled_video(width, height, resolution_label, receiver_ip, scaled, video_name):
    
    if scaled:
        filename = f"downscaled_{resolution_label}.yuv"
    else:
        filename = f"{video_name}.yuv" 
    
    
    gstreamer_command = [
        'gst-launch-1.0', 'filesrc', f'location={filename}',
        '!', 'rawvideoparse', 'format=i420',
        f'width={width}', f'height={height}', 'framerate=25/1',
        '!', 'rtpvrawpay',
        '!', 'udpsink', f'host={receiver_ip}', 'port=5000'
    ]
    print(f"Streaming {filename} to {receiver_ip}:5000...")
    subprocess.run(gstreamer_command)
    
def send_done_signal(receiver_ip, port=6001):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((receiver_ip, port))
            s.sendall("done".encode("utf-8"))
            print("'done' sent to receiver.")
    except Exception as e:
        print(f"Could not send 'done' to receiver: {e}")




if __name__ == "__main__":

    video_name = input("Enter name of videofile: ")
    print("")

    receiver_ip = input("Enter receiver IP: ")
    receiver_port = 6000
    print("")

    bandwidth = get_bandwidth_mbit(receiver_ip)

    width, height, resolution_label, info = determine_resolution_from_bandwidth(bandwidth)

    send_resolution_over_tcp(receiver_ip, receiver_port, width, height, bandwidth)
    
    scaled = bandwidth <= 630
    if scaled:
        run_gstreamer_pipeline(width, height, resolution_label, info)
    else:
        print("Measured uplink bandwidth supports original resolution. No downscaling needed.")
    
    stream_downscaled_video(width, height, resolution_label, receiver_ip, scaled, video_name)

    send_done_signal(receiver_ip)













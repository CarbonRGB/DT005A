import socket
import subprocess
import sys
import re
import threading
import os
import glob

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def start_iperf3_server():
    print("Starting iPerf3-server... (waiting for client to run bandwidth test)")
    try:
        result = subprocess.run(
            ['iperf3', '-s', '-1'],
            capture_output=True,
            text=True
        )
        print("iPerf3-server done and shutting down.")
        print(result.stdout)
    except Exception as e:
        print(f"Error running iPerf3-server: {e}")
        sys.exit(1)

def wait_for_resolution_metadata(host='0.0.0.0', port=6000):
    print(f"Waiting for TCP-metadata on port {port}...")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            s.listen(1)
            conn, addr = s.accept()
            with conn:
                print(f"Connected to client: {addr}")
                data = conn.recv(1024).decode('utf-8')
                print(f"Received metadata: {data}")

                match = re.findall(r'(\w+)=([\w\d]+)', data)
                metadata = dict(match)
                width = metadata.get("width")
                height = metadata.get("height")
                scaled = metadata.get("scaled", "false").lower() == "true"
                scale = int(metadata.get("scale", "1"))

                if width is None or height is None:
                    raise ValueError("Could not interpret resolution and/or if scaled or not.")

                print(f"Received resolution information and if scaled: width={width}, height={height}", scaled, scale)
                return int(width), int(height), scaled, scale
    except Exception as e:
        print(f"Error receiving metadata: {e}")
        sys.exit(1)

def run_gstreamer_receiver(width, height, output_filename="received_video.yuv", port=5000):
    print("Starting GStreamer pipeline to receive video...")
    
    # Create directory for received video
    output_folder = os.path.join(BASE_DIR, "received_video_stream")
    os.makedirs(output_folder, exist_ok=True)

    # Create full path
    full_output_path = os.path.join(output_folder, output_filename)
    
    # Delete previous video if it exists
    if os.path.exists(full_output_path):
        print(f"Video from previous stream found and is being erased: {full_output_path}")
        os.remove(full_output_path)    

    caps = (
        f"application/x-rtp, media=(string)video, clock-rate=(int)90000, encoding-name=(string)RAW, "
        f"sampling=(string)YCbCr-4:2:0, depth=(string)8, width=(string){width}, height=(string){height}"
    )

    command = [
        "gst-launch-1.0",
        "udpsrc", f"uri=udp://0.0.0.0:5000", f"caps={caps}",
        "!", "rtpvrawdepay",
        "!", "queue",
        "!", "videoconvert",
        "!", "filesink", f"location={full_output_path}"
    ]
    proc = subprocess.Popen(command)
    return proc


def wait_for_done_signal(proc, port=6001):
    print(f"Waiting TCP-termination signal on port {port}...")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("0.0.0.0", port))
        s.listen(1)
        conn, addr = s.accept()
        with conn:
            data = conn.recv(1024).decode('utf-8').strip()
            if data == "done":
                print("Signal 'done' received. Closing GStreamer-pipeline.")
                proc.terminate()
            else:
                print(f"Unknown message from {addr}: {data}")


def extract_frames_from_yuv(width, height, input_file="received_video.yuv", input_folder="received_video_stream", output_folder="lr_frames"):
    print("Extracting frames from received .yuv video...")

    # Create directory if it doesnt exist.
    output_folder = os.path.join(BASE_DIR, output_folder)
    os.makedirs(output_folder, exist_ok=True)

    # Delete old images if there are any.
    old_images = glob.glob(os.path.join(output_folder, "*.png"))
    if old_images:
        print(f"Erasing {len(old_images)} old images from {output_folder}/...")
        for image in old_images:
            os.remove(image)

    # Full path to input file.
    input_path = os.path.join(BASE_DIR, input_folder, input_file)

    command = [
        "ffmpeg",
        "-s:v", f"{width}x{height}",
        "-pix_fmt", "yuv420p",
        "-r", "25",
        "-i", input_path,
        os.path.join(output_folder, "frame_%04d.png")
    ]

    try:
        subprocess.run(command, check=True)
        print(f"Frames extracted to: {output_folder}/")
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed: {e}")
        

def run_gan_on_extracted_frames(scale, lr_folder="lr_frames", sr_folder="sr_frames"):
    print("Starting GAN-enhancement process on extracted images...")
    
    model_selection_map = {
        2: "fine-tuned_g_x2plus",
        4: "fine-tuned_g_x4plus"
    }

    model = model_selection_map.get(scale, "fine-tuned_g_x2plus")
    print(f"Model {model} selected.")
    if scale not in model_selection_map:
        print(f"Scale {scale} is not supported in this system. Standardmodel (x2) is selected.")
    

    # Create sr_folder_path if it doesnt exist
    sr_folder_path = os.path.join(BASE_DIR, sr_folder)
    os.makedirs(sr_folder_path, exist_ok=True)
    
    # Delete old SR-bilder
    old_sr_images = glob.glob(os.path.join(sr_folder_path, "*.png"))
    if old_sr_images:
        print(f"Deleting {len(old_sr_images)} old SR-images i {sr_folder_path}/..")
        for img in old_sr_images:
            os.remove(img)

    # Fetch all PNG-files in lr_folder_path
    lr_folder_path = os.path.join(BASE_DIR, lr_folder)
    lr_images = sorted(glob.glob(os.path.join(lr_folder_path, "*.png")))

    if not lr_images:
        print("Warning: No LR images found.")
        return

    for img_path in lr_images:
        print("")
        print(f"Processing image: {os.path.basename(img_path)}")

        command = [
            "python3",
            os.path.join(BASE_DIR, "inference_realesrgan.py"),
            "-n", model,
            "-i", img_path,
            "-o", sr_folder_path,
            "-s", str(scale)
        ]

        try:
            subprocess.run(command, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error occured processing image {img_path}: {e}")

    print("All images have been successfully upscaled.")
    print("")    

def create_sr_video_from_frames(sr_frame_folder="sr_frames", output_folder="sr_videos", output_name="sr_video.yuv", framerate=25, width=1920, height=1080):
    print("Recreating video from SR-images with ffmpeg...")

    # Create output-folder if it doesnt exist.
    sr_frame_folder_path = os.path.join(BASE_DIR, sr_frame_folder)
    output_folder_path = os.path.join(BASE_DIR, output_folder)
    os.makedirs(output_folder_path, exist_ok=True)
    
    # Delete existing video if it exists from previous runs.
    output_path = os.path.join(output_folder_path, output_name)
    if os.path.exists(output_path):
        print(f"Found existing SR video, erasing: {output_path}")
        os.remove(output_path)

    command = [
        "ffmpeg",
        "-framerate", str(framerate),
        "-i", os.path.join(sr_frame_folder_path, "frame_%04d_out.png"),
        "-c:v", "rawvideo",
        "-pix_fmt", "yuv420p",
        "-s", f"{width}x{height}",
        output_path
    ]

    try:
        subprocess.run(command, check=True)
        print(f"Video successfully recreated and saved as: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"Video recreation using ffmpeg failed: {e} ")

        
def play_yuv_video_with_gstreamer(is_gan, filename="sr_video.yuv", folder="sr_videos", width=1920, height=1080, framerate=25):
    print("Video is being played...")

    if is_gan:
        full_path = os.path.join(BASE_DIR, folder, filename)
    else:
        full_path = os.path.join(BASE_DIR, "received_video_stream", "received_video.yuv")
        

    command = [
        "gst-launch-1.0",
        "filesrc", f"location={full_path}",
        "!", "videoparse",
        "format=2",  # format=i420
        f"width={width}",
        f"height={height}",
        f"framerate={framerate}/1",
        "!", "autovideosink"
    ]

    try:
        subprocess.run(command, check=True)
        print("Video ended.")
    except subprocess.CalledProcessError as e:
        print(f"Error: Could not play video: {e}")



if __name__ == "__main__":
    start_iperf3_server()
    width, height, scaled, scale = wait_for_resolution_metadata()
    process = run_gstreamer_receiver(width, height)
    wait_for_done_signal(process)
    
    if scaled:
        extract_frames_from_yuv(width, height)
        run_gan_on_extracted_frames(scale)
        create_sr_video_from_frames()
        play_yuv_video_with_gstreamer(is_gan=True)
    else:
        print("Video with original resolution received. No enhancement will be executed.")
        play_yuv_video_with_gstreamer(is_gan=False)
    
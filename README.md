
# WebRTC Video Streaming Application

## Overview
This project implements a WebRTC-based video streaming application with signaling over WebSockets. It supports both sending and receiving video streams, with the option to save the received video to a file. The application uses `aiortc` for WebRTC functionality, `websockets` for signaling, `OpenCV` for video processing, and `Matplotlib` for real-time video display.

## Features
- **Sender**: Captures video from a specified source (e.g., webcam or file) and streams it via WebRTC.
- **Receiver**: Displays the received video stream in real-time using Matplotlib and optionally saves it to a file (`received_output.avi`).
- **Signaling**: Uses a WebSocket server to exchange SDP and ICE candidates between sender and receiver.
- **Cross-Platform**: Automatically detects the default video source based on the operating system (Linux, macOS, Windows).
- **Graceful Shutdown**: Handles connection closure and system signals (e.g., Ctrl+C) for clean termination.
- **Video Track Monitoring**: Automatically closes the sender's connection when a stored video file ends.

## Requirements
- Python 3.7+
- Required Python packages:
  ```bash
  pip install aiortc websockets opencv-python matplotlib
  ```

## Usage
1. **Run the Signaling Server**:
   Start the WebSocket signaling server to facilitate communication between sender and receiver.
   ```python
   webrtc = WebRTCWrapper()
   asyncio.run(webrtc.start_signaling_server())
   ```
   By default, the server runs on `ws://localhost:8765`. You can customize the URL and port via the `WebRTCWrapper` constructor.

2. **Run the Sender**:
   Start the sender to capture and stream video from a specified source (e.g., webcam or video file).
   ```python
   webrtc = WebRTCWrapper(source="path/to/video.mp4")  # or 0 for default webcam
   asyncio.run(webrtc.run_sender())
   ```
   If no source is specified, the default video source is used based on the OS.

3. **Run the Receiver**:
   Start the receiver to display the incoming video stream and optionally save it.
   ```python
   webrtc = WebRTCWrapper(save_output=True)  # Set to True to save the video
   asyncio.run(webrtc.run_receiver())
   ```
   - The video is displayed in a Matplotlib window.
   - Press `q` to close the display window and terminate the connection.
   - If `save_output=True`, the received video is saved as `received_output.avi`.

4. **Running All Components**:
   Typically, the signaling server, sender, and receiver should run in separate processes or terminals. For example:
   - Terminal 1: Run the signaling server.
   - Terminal 2: Run the sender.
   - Terminal 3: Run the receiver.

## Configuration
The `WebRTCWrapper` class accepts the following parameters:
- `signaling_server_url`: WebSocket server URL (default: `ws://localhost:8765`).
- `port`: Port for the signaling server (default: `8765`).
- `source`: Video source (e.g., camera index, device path, or video file path). If not provided, a default source is selected based on the OS.
- `save_output`: Boolean to enable saving the received video (default: `False`).

## Notes
- **Video Source**: Ensure the specified video source is accessible. For webcams, use the appropriate device index (e.g., `0` for the default camera on Windows) or path (e.g., `/dev/video0` on Linux).
- **Dependencies**: Install all required packages before running the application. OpenCV may require additional system dependencies (e.g., `libavcodec` for video file support).
- **Performance**: Real-time display with Matplotlib may introduce slight latency. For production use, consider alternative display methods (e.g., OpenCV's `imshow`).
- **Error Handling**: The application includes logging for debugging and handles common errors like connection timeouts and stream termination.
- **File Saving**: When `save_output=True`, the received video is saved in AVI format using the XVID codec. Ensure sufficient disk space and write permissions.

## Example
To stream a video file to a receiver that displays and saves the stream:
1. Start the signaling server:
   ```bash
   python script.py  # Assuming the script contains the signaling server code
   ```
2. Start the sender with a video file:
   ```bash
   python script.py --source video.mp4
   ```
3. Start the receiver with video saving enabled:
   ```bash
   python script.py --save_output
   ```

## Limitations
- The application assumes a single sender and receiver. For multiple clients, the signaling server logic would need to be extended.
- Audio tracks are supported but not displayed (only forwarded if present).
- The Matplotlib-based display may not be optimal for high-frame-rate streams.

## Troubleshooting
- **Connection Issues**: Ensure the signaling server is running and accessible at the specified URL/port.
- **Video Source Errors**: Verify the video source is correct and accessible (e.g., test with `cv2.VideoCapture`).
- **Timeout Errors**: Check network connectivity and ensure the sender and receiver are started within 30 seconds of each other.
- **Dependencies**: Install all required Python packages and system dependencies for OpenCV.

## License
This project is licensed under the GNU General Public License v3.0. You are free to use, modify, and distribute this software in accordance with the terms of the GPL-3.0. See the LICENSE file for full details.


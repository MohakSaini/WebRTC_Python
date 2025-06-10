import asyncio
import websockets
import matplotlib.pyplot as plt
import logging
import json
import signal
import platform
import cv2
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamError
from aiortc.contrib.media import MediaPlayer

# Configure logging to display informational messages
logging.basicConfig(level=logging.INFO)

class WebRTCWrapper:
    """
    A class to handle WebRTC video streaming with signaling over WebSockets.
    Supports sending and receiving video streams, with optional video saving.
    """
    def __init__(self, signaling_server_url="ws://localhost:8765", port=8765, source=None, save_output=False):
        """
        Initialize the WebRTCWrapper.

        Args:
            signaling_server_url (str): URL of the WebSocket signaling server.
            port (int): Port for the signaling server.
            source (str or int): Video source (e.g., camera device or file path).
            save_output (bool): Whether to save received video to a file.
        """
        self.signaling_server_url = signaling_server_url
        self.port = port
        self.source = source or self.get_default_source()
        self.save_output = save_output
        # Dictionary to store WebSocket connections for sender and receiver
        self.clients = {"sender": None, "receiver": None}
        # Queues to store messages when the target client is not connected
        self.message_queue = {"sender": [], "receiver": []}
        self.sender_task = None

    def get_default_source(self):
        """
        Determine the default video source based on the operating system.

        Returns:
            str or int: Default video source (device path or index).

        Raises:
            RuntimeError: If the operating system is not supported.
        """
        system = platform.system()
        if system == "Linux":
            return "/dev/video0"  # Default camera on Linux
        elif system == "Darwin":
            return "default:none"  # Default camera on macOS
        elif system == "Windows":
            return 0  # Default camera index on Windows
        else:
            raise RuntimeError("Unsupported OS")

    async def start_signaling_server(self):
        """
        Start a WebSocket signaling server to exchange SDP and ICE candidates
        between sender and receiver.
        """
        async def handler(websocket):
            """
            Handle WebSocket connections for signaling.

            Args:
                websocket: WebSocket connection object.
            """
            try:
                # Receive the role (sender or receiver) from the client
                role = await websocket.recv()
                logging.info(f"{role} connected")

                # Validate the role
                if role not in self.clients:
                    await websocket.send("Invalid role")
                    return

                # Store the WebSocket connection for the role
                self.clients[role] = websocket

                # Send any queued messages for this role
                while self.message_queue[role]:
                    await websocket.send(self.message_queue[role].pop(0))

                # Continuously receive and forward messages
                while True:
                    message = await websocket.recv()
                    # Determine the target role (opposite of the current role)
                    target = "receiver" if role == "sender" else "sender"
                    target_ws = self.clients.get(target)
                    if target_ws:
                        # Forward the message to the target
                        await target_ws.send(message)
                    else:
                        # Queue the message if the target is not connected
                        logging.warning(f"{target} not connected — queueing message")
                        self.message_queue[target].append(message)

            except websockets.exceptions.ConnectionClosed:
                # Handle client disconnection
                logging.info(f"{role} disconnected")
                self.clients[role] = None

        # Start the WebSocket server
        async with websockets.serve(handler, "0.0.0.0", self.port):
            logging.info(f"Signaling server running on ws://0.0.0.0:{self.port}")
            await asyncio.Future()  # Keep the server running indefinitely

    async def run_sender(self):
        """
        Run the sender side of the WebRTC connection, which captures and sends video.
        Closes the connection when a stored video file ends.
        """
        # Create a new RTCPeerConnection
        pc = RTCPeerConnection()
        # Initialize the media player with the specified video source
        player = MediaPlayer(self.source)

        # Add video track if available
        if player.video:
            pc.addTrack(player.video)
            logging.info("Added video track")
            # Store the video track to monitor its state
            video_track = player.video

        # Add audio track if available
        if player.audio:
            pc.addTrack(player.audio)
            logging.info("Added audio track")

        # Create and set the local offer
        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        try:
            # Connect to the signaling server
            async with websockets.connect(self.signaling_server_url) as websocket:
                # Identify as the sender
                await websocket.send("sender")
                # Send the offer SDP
                await websocket.send(json.dumps({
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp
                }))

                # Wait for the answer SDP from the receiver
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                except asyncio.TimeoutError:
                    logging.error("Timeout waiting for answer SDP")
                    return

                # Set the remote answer SDP
                data = json.loads(message)
                answer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                await pc.setRemoteDescription(answer)

                # Monitor the video track to detect when it ends
                if player.video:
                    async def monitor_video_track():
                        """
                        Monitor the video track and close the connection when it ends.
                        """
                        try:
                            while video_track.readyState == "live":
                                await asyncio.sleep(0.1)  # Check frequently
                            logging.info("Video track ended, closing connection")
                            await pc.close()
                        except Exception as e:
                            logging.error(f"Error monitoring video track: {e}")

                    # Start monitoring the video track
                    asyncio.ensure_future(monitor_video_track())

                # Keep the connection alive until closed
                while pc.iceConnectionState != "closed":
                    await asyncio.sleep(1)
        except Exception as e:
            logging.error(f"Sender connection error: {e}")
        finally:
            # Clean up the connection
            await pc.close()
            logging.info("Sender connection closed")

    async def run_receiver(self):
        """
        Run the receiver side of the WebRTC connection, which displays and optionally
        saves the received video stream.
        """
        # Create a new RTCPeerConnection
        pc = RTCPeerConnection()
        # Initialize matplotlib for real-time video display
        plt.ion()
        fig, ax = plt.subplots()
        img_display = None

        video_writer = None

        @pc.on("track")
        def on_track(track):
            """
            Handle incoming media tracks.

            Args:
                track: The received media track (video or audio).
            """
            logging.info(f"Receiving {track.kind} track")

            if track.kind == "video":
                async def display_video():
                    """
                    Display the received video frames in real-time and optionally save them.
                    """
                    nonlocal img_display, video_writer
                    try:
                        while True:
                            # Receive a video frame
                            frame = await track.recv()
                            img = frame.to_ndarray(format="bgr24")
                            rgb_img = img[..., ::-1]  # Convert BGR to RGB for display

                            # Initialize video writer if saving is enabled
                            if self.save_output and video_writer is None:
                                height, width = img.shape[:2]
                                video_writer = cv2.VideoWriter(
                                    "received_output.avi",
                                    cv2.VideoWriter_fourcc(*"XVID"),
                                    20,
                                    (width, height)
                                )

                            # Write frame to video file if saving
                            if self.save_output and video_writer:
                                video_writer.write(img)

                            # Display the frame
                            if img_display is None:
                                img_display = ax.imshow(rgb_img)
                            else:
                                img_display.set_data(rgb_img)
                            plt.draw()
                            plt.pause(0.001)
                    except MediaStreamError:
                        # Handle stream termination
                        logging.warning("Stream ended or connection closed")
                        await pc.close()
                        plt.close(fig)
                        if video_writer:
                            video_writer.release()

                # Start the video display coroutine
                asyncio.ensure_future(display_video())

        def on_key(event):
            """
            Handle key press events to close the display window.

            Args:
                event: Matplotlib key press event.
            """
            if event.key == "q":
                logging.info("'q' pressed, closing window")
                plt.close(fig)
                asyncio.create_task(pc.close())

        # Connect the key press event handler
        fig.canvas.mpl_connect("key_press_event", on_key)

        try:
            # Connect to the signaling server
            async with websockets.connect(self.signaling_server_url) as websocket:
                # Identify as the receiver
                await websocket.send("receiver")
                logging.info("Connected to signaling server")

                # Wait for the offer SDP from the sender
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=30)
                except asyncio.TimeoutError:
                    logging.error("Timeout waiting for offer SDP")
                    return

                # Set the remote offer SDP
                data = json.loads(message)
                offer = RTCSessionDescription(sdp=data["sdp"], type=data["type"])
                await pc.setRemoteDescription(offer)

                # Create and send the answer SDP
                answer = await pc.createAnswer()
                await pc.setLocalDescription(answer)
                await websocket.send(json.dumps({
                    "type": pc.localDescription.type,
                    "sdp": pc.localDescription.sdp
                }))
                logging.info("Sent answer SDP")

                def on_iceconnectionstatechange():
                    """
                    Handle changes in ICE connection state.
                    """
                    if pc.iceConnectionState == "closed":
                        logging.warning("Connection closed by peer")
                        plt.close(fig)
                        asyncio.create_task(pc.close())

                # Set the ICE connection state change handler
                pc.on("iceconnectionstatechange", on_iceconnectionstatechange)

                def signal_handler(sig, frame):
                    """
                    Handle system signals (e.g., Ctrl+C) to close the connection.

                    Args:
                        sig: Signal number.
                        frame: Current stack frame.
                    """
                    logging.info("Signal received, closing connection")
                    asyncio.create_task(pc.close())
                    asyncio.get_event_loop().stop()

                # Add signal handler for clean shutdown
                loop = asyncio.get_event_loop()
                loop.add_signal_handler(signal.SIGINT, signal_handler, signal.SIGINT, None)

                # Keep the connection alive until closed
                while pc.iceConnectionState != "closed":
                    await asyncio.sleep(1)

        except Exception as e:
            logging.error(f"Receiver error: {e}")
        finally:
            # Clean up the connection and close the display
            await pc.close()
            plt.close(fig)
            logging.info("Receiver connection closed")

"""
Usage Guide for WebRTC Video Streaming Application

This script implements a WebRTC-based video streaming application using a WebSocket
signaling server to exchange SDP and ICE candidates between a sender and a receiver.
The sender captures video from a camera or a stored video file and streams it to the
receiver, which displays the video in real-time and optionally saves it to a file.
When streaming a stored video file, the connection is automatically closed when the
video ends.

### Prerequisites
1. **Python Version**: Python 3.7 or higher.
2. **Dependencies**: Install the required Python packages using pip:
   ```bash
   pip install aiortc websockets matplotlib opencv-python numpy
   ```
3. **Camera or Video File**: Ensure a camera is connected for live streaming or provide a valid video file path (e.g., `.mp4`, `.avi`) for stored video streaming.
4. **Operating System**: Supported on Linux, macOS, and Windows.

### How to Run
1. **Start the Signaling Server**:
   - The signaling server facilitates communication between the sender and receiver.
   - Run the following code in a Python script or terminal:
     ```python
     import asyncio
     from webrtc_video_stream import WebRTCWrapper

     async def main():
         wrapper = WebRTCWrapper()
         await wrapper.start_signaling_server()

     asyncio.run(main())
     ```
   - This starts the server on `ws://localhost:8765` (default port).
   - Keep this running in one terminal.

2. **Run the Sender**:
   - The sender streams video from a camera or a stored video file.
   - For a camera, run:
     ```python
     import asyncio
     from webrtc_video_stream import WebRTCWrapper

     async def main():
         wrapper = WebRTCWrapper()
         await wrapper.run_sender()

     asyncio.run(main())
     ```
   - For a stored video file (e.g., `video.mp4`), specify the source:
     ```python
     import asyncio
     from webrtc_video_stream import WebRTCWrapper

     async def main():
         wrapper = WebRTCWrapper(source="path/to/video.mp4")
         await wrapper.run_sender()

     asyncio.run(main())
     ```
   - If a stored video is used, the connection will automatically close when the video ends.

3. **Run the Receiver**:
   - The receiver displays the streamed video in a matplotlib window and can save it to a file.
   - Run:
     ```python
     import asyncio
     from webrtc_video_stream import WebRTCWrapper

     async def main():
         wrapper = WebRTCWrapper(save_output=True)  # Set to True to save video
         await wrapper.run_receiver()

     asyncio.run(main())
     ```
   - A window will pop up displaying the video stream.
   - Press `q` in the display window to close it manually.
   - If `save_output=True`, the received video is saved as `received_output.avi`.
   - The receiver will automatically close when the sender's video ends (for stored videos).

### Running on the Same Machine
- You can run the signaling server, sender, and receiver on the same machine.
- Use separate terminal windows for each component.
- Ensure the `signaling_server_url` and `port` are consistent across all components (default: `ws://localhost:8765`, port `8765`).

### Running on Different Machines
- **Signaling Server**: Run the signaling server on a machine accessible to both sender and receiver.
  - Update the `signaling_server_url` in the sender and receiver to point to the server's IP address, e.g., `ws://192.168.1.100:8765`.
  - Ensure the port (e.g., `8765`) is open in the server's firewall.
- **Sender and Receiver**: Run the sender and receiver on separate machines, specifying the signaling server's URL:
  ```python
  wrapper = WebRTCWrapper(signaling_server_url="ws://192.168.1.100:8765")
  ```

### Notes
- **Video End Detection**: When streaming a stored video file, the sender monitors the video track's `readyState`. When the track ends (state changes from `live` to `ended`), the connection is automatically closed, and the receiver will also close its display window.
- **Timeout**: The sender and receiver wait up to 30 seconds for SDP messages. If no connection is established, they will timeout and exit.
- **Video Source**: The default camera is automatically selected based on the OS. For Linux, it uses `/dev/video0`; for macOS, `default:none`; for Windows, camera index `0`. Specify a video file path (e.g., `video.mp4`) for stored video streaming.
- **Saving Video**: Set `save_output=True` in the receiver to save the video as `received_output.avi` in the current directory.
- **Closing the Application**:
  - Receiver: Press `q` in the matplotlib window or send a `SIGINT` (Ctrl+C) to the terminal. The receiver also closes automatically when the sender's video ends.
  - Sender: For stored videos, the connection closes automatically when the video ends. For live streams, use `SIGINT` (Ctrl+C) to stop.
  - Signaling Server: Use `SIGINT` (Ctrl+C) to stop.
- **Error Handling**: Check the console logs for errors (e.g., video file not found, camera not accessible, signaling server not reachable).

### Example Workflow
1. Open three terminals.
2. In Terminal 1, run the signaling server:
   ```bash
   python -c "import asyncio; from webrtc_video_stream import WebRTCWrapper; asyncio.run(WebRTCWrapper().start_signaling_server())"
   ```
3. In Terminal 2, run the sender with a stored video:
   ```bash
   python -c "import asyncio; from webrtc_video_stream import WebRTCWrapper; asyncio.run(WebRTCWrapper(source='path/to/video.mp4').run_sender())"
   ```
4. In Terminal 3, run the receiver:
   ```bash
   python -c "import asyncio; from webrtc_video_stream import WebRTCWrapper; asyncio.run(WebRTCWrapper(save_output=True).run_receiver())"
   ```
5. The video will stream, and the connection will close automatically when the video ends. Alternatively, press `q` in the receiver's window to exit early.

### Troubleshooting
- **Video File Not Found**: Ensure the video file path is correct and the file is accessible. Supported formats include `.mp4`, `.avi`, etc.
- **Camera Not Found**: Ensure the camera is connected and the `source` is correct. On Linux, list devices with `ls /dev/video*`. On Windows, try different indices (e.g., `0`, `1`).
- **Signaling Server Not Reachable**: Verify the server is running and the URL/port are correct. Check firewall settings if on different machines.
- **No Video Display**: Ensure the sender is running before the receiver, and the signaling server is active.
- **Dependencies**: Ensure all required packages are installed (`aiortc`, `websockets`, etc.).

This application provides a simple way to stream video over WebRTC, with automatic connection closure for stored video files.
"""
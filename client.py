import asyncio
import inspect
import json
import websockets
import logging
import os
import sys
import agent_func  # Your fully operational Selenium code on the client machine.

# Configure logging to show the timestamp, log level, and message.
logging.basicConfig(
    level=logging.DEBUG,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

# Build a mapping between function names and the actual implementations.
FUNCTION_MAP = {
    "create_driver": agent_func.create_driver,
    "stop_driver": agent_func.stop_driver,
    "send_keys": agent_func.send_keys,
    "exists": agent_func.exists,
    "does_not_exist": agent_func.does_not_exist,
    "click": agent_func.click,
    "get_page": agent_func.get_page,
}

# -------------------------------------------------------------------
# MESSAGE HANDLER
# -------------------------------------------------------------------
async def handle_message(message):
    """
    Processes an incoming message, executes the requested function,
    and returns the response as a JSON string.
    """
    logging.debug(f"Processing received message: {message}")
    response_dict = {}
    try:
        if not message.strip():  # Check for empty or whitespace-only messages
            raise ValueError("Received an empty or invalid message.")

        data = json.loads(message)
        function_name = data.get("function")
        args = data.get("args", [])
        kwargs = data.get("kwargs", {})
        logging.debug(f"Parsed data - function: {function_name}, args: {args}, kwargs: {kwargs}")

        # Special handling for listing available methods.
        if function_name == "list_available_methods":
            method_details = []
            for name, func in FUNCTION_MAP.items():
                sig = inspect.signature(func)
                arg_names = [param.name for param in sig.parameters.values() if param.name != "_run_test_id"]
                method_details.append({
                    "name": name,
                    "args": arg_names,
                    "doc": func.__doc__ or ""
                })
            response_dict = {"status": "success", "methods": method_details}
            logging.debug(f"Prepared list_available_methods response: {response_dict}")

        # If the requested function exists, call it.
        elif function_name in FUNCTION_MAP:
            func = FUNCTION_MAP[function_name]
            logging.debug(f"Calling function '{function_name}' with args: {args} and kwargs: {kwargs}")
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            response_dict = {"status": "success", "result": result}
            logging.debug(f"Function '{function_name}' executed successfully.")
        else:
            response_dict = {"status": "error", "error": f"Unknown function: {function_name}"}
            logging.warning(f"Function not found: {function_name}")

    except json.JSONDecodeError:
        logging.error(f"Failed to decode JSON from message: {message}")
        response_dict = {"status": "error", "error": "Invalid JSON received"}
    except Exception as e:
        logging.error(f"Error processing message: {e}", exc_info=True)
        response_dict = {"status": "error", "error": str(e)}

    response_json = json.dumps(response_dict)
    logging.debug(f"Returning JSON response: {response_json}")
    return response_json

# -------------------------------------------------------------------
# WEBSOCKET CLIENT HANDLER
# -------------------------------------------------------------------
async def connect_to_backend(uri):
    logging.info(f"Connecting to WebSocket backend at {uri}")
    while True: # Add a loop for reconnection attempts
        try:
            async with websockets.connect(uri) as ws:
                logging.info("Connection established with backend.")
                try:
                    while True: # Keep listening after connection
                        message = await ws.recv()
                        logging.debug(f"Message received from backend: {message}")

                        # Handle the message and get the JSON response string
                        response_json = await handle_message(message) # Pass only the message

                        # Send the JSON response string back
                        logging.debug(f"Sending response to backend: {response_json}")
                        await ws.send(response_json) # Send the returned JSON string

                except websockets.exceptions.ConnectionClosed as e:
                    logging.error(f"Connection closed: {e.code} {e.reason}")
                    break # Exit inner loop to attempt reconnection
                except Exception as e:
                    logging.error("Unexpected error during active connection", exc_info=True)
                    # Attempt to send an error back if possible
                    try:
                        error_response = json.dumps({"status": "error", "error": f"Client-side error: {str(e)}"})
                        await ws.send(error_response)
                    except Exception:
                        logging.error("Failed to send error message before closing.")
                    break # Exit inner loop

        except (websockets.exceptions.WebSocketException, OSError) as e:
            logging.error(f"Failed to connect or connection lost: {e}")
        except Exception as e:
            logging.error("Unexpected error in connection logic", exc_info=True)

        logging.info("Attempting to reconnect in 10 seconds...")
        await asyncio.sleep(10) # Wait before retrying connection

# -------------------------------------------------------------------
# MAIN
# -------------------------------------------------------------------
async def main():
    backend_uri = 'wss://beta.barkoagent.com/ws/' + os.getenv("BACKEND_WS_URI", "default_client_id") # Provide a default for testing
    if not backend_uri.startswith("ws://") and not backend_uri.startswith("wss://"):
        logging.error(f"Invalid BACKEND_WS_URI: {backend_uri}. It must start with ws:// or wss://")
        return # Exit if URI is invalid

    logging.info(f"Using backend WebSocket URI: {backend_uri}")
    while True:
        await connect_to_backend(backend_uri)

if __name__ == "__main__":
    # --- Add environment variable setup if needed ---
    # Example: Set a default URI if the environment variable isn't present
    # This is useful for local testing. Replace 'your_default_client_id'
    # with an actual ID or mechanism to get one if required by your backend.
    if not os.getenv("BACKEND_WS_URI"):
        backend_uri = input("BACKEND_WS_URI not set. Please enter BACKEND_WS_URI: ")
        if not backend_uri:
            logging.error("No BACKEND_WS_URI provided, exiting.")
            sys.exit(1)
        os.environ["BACKEND_WS_URI"] = backend_uri
    # --- ---

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Client stopped manually.")
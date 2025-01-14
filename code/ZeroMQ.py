import zmq

def main():
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.connect("tcp://127.0.0.1:5556")  # Use the same port as the server
    socket.setsockopt_string(zmq.SUBSCRIBE, "")  # Subscribe to all topics

    print("Listening for timestamps...")
    while True:
        message = socket.recv_string()
        print(f"Received message: {message}")

if __name__ == "__main__":
    main()

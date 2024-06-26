from flask import Flask, Response
from prometheus_client import start_http_server, Gauge, CollectorRegistry, generate_latest
import subprocess
import socket
import re
import os
import logging
import json

from dotenv import load_dotenv # type: ignore
load_dotenv()

app = Flask(__name__)

# Configure the logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define the working directory
#current_dir = os.path.dirname(os.path.abspath(__file__))
#working_directory = os.getenv("node_path") or f'{current_dir}/../ceremonyclient/node'

# Systemd name
service_name= os.getenv("service_name") or 'quilibrium'

# Define the registry
registry = CollectorRegistry()

# Container Name
container_name = 'quilibrium'

docker_path = "/usr/bin/docker"

# Define custom metrics
peer_score_metric = Gauge('quilibrium_peer_score', 'Peer score of the node', ['peer_id', 'hostname'], registry=registry)
max_frame_metric = Gauge('quilibrium_max_frame', 'Max frame of the node', ['peer_id', 'hostname'], registry=registry)
unclaimed_balance_metric = Gauge('quilibrium_unclaimed_balance', 'Unclaimed balance of the node', ['peer_id', 'hostname'], registry=registry)
peer_store_count_metric = Gauge('quilibrium_peer_store_count', 'Peers in store', ['peer_id', 'hostname'], registry=registry)
network_peer_count_metric = Gauge('quilibrium_network_peer_count', 'Network peer count', ['peer_id', 'hostname'], registry=registry)
proof_increment_metric = Gauge('quilibrium_proof_increment', 'Proof increment', ['peer_id', 'hostname'], registry=registry)
proof_time_taken_metric = Gauge('quilibrium_proof_time_taken', 'Proof time taken', ['peer_id', 'hostname'], registry=registry)


def is_container_running(container_name):
    """
    Check if a Docker container is running.

    Args:
        container_name (str): The name of the Docker container.

    Returns:
        bool: True if the container is running, False otherwise.
    """
    try:
        # Run the command to check if the container is running
        output = subprocess.check_output(['docker', 'ps', '-q', '-f', 'name=' + container_name])
        # If the container is running, the command will return the container ID
        if output.decode().strip():
            return True
        else:
            return False
    except subprocess.CalledProcessError:
        # If the container is not running, the command will raise an error
        return False

def fetch_data_from_node(container_name):
    try:
        if is_container_running(container_name):
            result = subprocess.run(['docker', 'exec', container_name, 'node', '-node-info'], capture_output=True, text=True)
            output = result.stdout

            peer_id_match = re.search(r'Peer ID: (\S+)', output)
            peer_id = peer_id_match.group(1) if peer_id_match else 'unknown'

            peer_score_match = re.search(r'Peer Score: (\d+)', output)
            peer_score = float(peer_score_match.group(1)) if peer_score_match else 0

            max_frame_match = re.search(r'Max Frame: (\d+)', output)
            max_frame = float(max_frame_match.group(1)) if max_frame_match else 0

            unclaimed_balance_match = re.search(r'Unclaimed balance: ([\d\.]+)', output)
            unclaimed_balance = float(unclaimed_balance_match.group(1)) if unclaimed_balance_match else 0

            hostname = socket.gethostname()

            peer_score_metric.labels(peer_id=peer_id, hostname=hostname).set(peer_score)
            max_frame_metric.labels(peer_id=peer_id, hostname=hostname).set(max_frame)
            unclaimed_balance_metric.labels(peer_id=peer_id, hostname=hostname).set(unclaimed_balance)

        return peer_id, hostname

    except Exception as e:
        logger.error(f"Error fetching data from command: {e}")
        return None, None

def fetch_data_from_logs(peer_id, hostname, container_name):
    try:
        output = subprocess.run(['docker', 'logs', container_name, '--since=5m'], capture_output=True, text=True)
        output = output.stderr.splitlines()

        peer_store_count = None
        network_peer_count = None
        proof_increment = None
        proof_time_taken = None

        for line in output:
            if peer_store_count is None and 'peers in store' in line:
                peer_store_count_match = re.search(r'"peer_store_count":(\d+)', line)
                network_peer_count_match = re.search(r'"network_peer_count":(\d+)', line)
                if peer_store_count_match and network_peer_count_match:
                    peer_store_count = int(peer_store_count_match.group(1))
                    network_peer_count = int(network_peer_count_match.group(1))
                    peer_store_count_metric.labels(peer_id=peer_id, hostname=hostname).set(peer_store_count)
                    network_peer_count_metric.labels(peer_id=peer_id, hostname=hostname).set(network_peer_count)
            if proof_increment is None and 'completed duration proof' in line:
                proof_increment_match = re.search(r'"increment":(\d+)', line)
                proof_time_taken_match = re.search(r'"time_taken":([\d\.]+)', line)
                if proof_increment_match and proof_time_taken_match:
                    proof_increment = int(proof_increment_match.group(1))
                    proof_time_taken = float(proof_time_taken_match.group(1))
                    proof_increment_metric.labels(peer_id=peer_id, hostname=hostname).set(proof_increment)
                    proof_time_taken_metric.labels(peer_id=peer_id, hostname=hostname).set(proof_time_taken)
            if (peer_store_count is not None and network_peer_count is not None and
                proof_increment is not None and proof_time_taken is not None):
                break

    except Exception as e:
        logger.error(f"Error fetching data from logs: {e}")

@app.route('/metrics')
def metrics():
    peer_score_metric.clear()
    max_frame_metric.clear()
    unclaimed_balance_metric.clear()
    peer_store_count_metric.clear()
    network_peer_count_metric.clear()
    proof_increment_metric.clear()
    proof_time_taken_metric.clear()

    peer_id, hostname = fetch_data_from_node(container_name)
    if peer_id and hostname:
        fetch_data_from_logs(peer_id, hostname, container_name)
    return Response(generate_latest(registry), mimetype='text/plain')

if __name__ == '__main__':
    start_http_server(8000)
    app.run(host='0.0.0.0', port=5001)

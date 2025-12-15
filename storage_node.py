"""
Distributed File System - Storage Node
Menyimpan file dan berkomunikasi dengan naming service
"""

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import hashlib
import threading
import time
import requests
import shutil
import argparse

app = Flask(__name__)
CORS(app)

# Configuration
NODE_ID = None
STORAGE_DIR = None
NAMING_SERVICE_URL = "http://localhost:5000"
MAX_STORAGE_SIZE =  None #10 * 1024 * 1024 #10 MB limit for testing (set to None for unlimited)

class StorageNode:
    def __init__(self, node_id, storage_dir):
        self.node_id = node_id
        self.storage_dir = storage_dir
        self.node_address = None
        self.max_storage = MAX_STORAGE_SIZE
        
        # Buat directory jika belum ada
        os.makedirs(storage_dir, exist_ok=True)
        
    def calculate_checksum(self, filepath):
        """Hitung SHA-256 checksum file"""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def save_file(self, file_id, file_data, filename=None):
        """Simpan file ke storage"""
        filepath = os.path.join(self.storage_dir, file_id)
        
        with open(filepath, 'wb') as f:
            f.write(file_data)
        
        # Simpan metadata filename jika ada
        if filename:
            metadata_filepath = filepath + ".meta"
            with open(metadata_filepath, 'w') as f:
                f.write(filename)
        
        checksum = self.calculate_checksum(filepath)
        file_size = os.path.getsize(filepath)
        
        return {
            "filepath": filepath,
            "checksum": checksum,
            "size": file_size
        }
    
    def get_file(self, file_id):
        """Ambil file dari storage"""
        filepath = os.path.join(self.storage_dir, file_id)
        
        if os.path.exists(filepath):
            return filepath
        return None
    
    def get_file_metadata(self, file_id):
        """Ambil metadata file (original filename)"""
        metadata_filepath = os.path.join(self.storage_dir, file_id + ".meta")
        
        if os.path.exists(metadata_filepath):
            with open(metadata_filepath, 'r') as f:
                return f.read().strip()
        return None
    
    def delete_file(self, file_id):
        """Hapus file dari storage"""
        filepath = os.path.join(self.storage_dir, file_id)
        meta_filepath = filepath + ".meta"
        
        file_deleted = False
        if os.path.exists(filepath):
            os.remove(filepath)
            file_deleted = True
        
        # Hapus file .meta juga jika ada
        if os.path.exists(meta_filepath):
            os.remove(meta_filepath)
        
        return file_deleted
    
    def get_available_space(self):
        """Dapatkan available space (terbatas atau unlimited)"""
        if self.max_storage is None:
            # Unlimited - gunakan disk space
            stat = shutil.disk_usage(self.storage_dir)
            return stat.free
        else:
            # Limited storage - hitung dari usage saat ini
            used_space = self.get_used_space()
            available = self.max_storage - used_space
            return max(0, available)  # Return 0 jika sudah penuh
    
    def get_used_space(self):
        """Hitung total space yang digunakan"""
        total_size = 0
        for item in os.listdir(self.storage_dir):
            item_path = os.path.join(self.storage_dir, item)
            if os.path.isfile(item_path):
                total_size += os.path.getsize(item_path)
        return total_size
    
    def get_file_count(self):
        """Hitung jumlah file"""
        return len([f for f in os.listdir(self.storage_dir) 
                   if os.path.isfile(os.path.join(self.storage_dir, f))])
    
    def register_with_naming_service(self, node_address):
        """Register node ke naming service"""
        self.node_address = node_address
        
        try:
            response = requests.post(
                f"{NAMING_SERVICE_URL}/api/nodes/register",
                json={
                    "node_id": self.node_id,
                    "node_address": node_address
                },
                timeout=5
            )
            
            if response.status_code == 200:
                print(f"✅ Registered with naming service: {self.node_id}")
                return True
            else:
                print(f"❌ Failed to register: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Error connecting to naming service: {e}")
            return False
    
    def send_heartbeat(self):
        """Kirim heartbeat ke naming service"""
        try:
            response = requests.post(
                f"{NAMING_SERVICE_URL}/api/nodes/heartbeat",
                json={
                    "node_id": self.node_id,
                    "available_space": self.get_available_space(),
                    "file_count": self.get_file_count()
                },
                timeout=5
            )
            
            if response.status_code == 200:
                return True
            else:
                print(f"⚠️  Heartbeat failed: {response.text}")
                return False
                
        except Exception as e:
            print(f"⚠️  Heartbeat error: {e}")
            return False
    
    def confirm_upload(self, file_id, checksum):
        """Konfirmasi upload ke naming service"""
        try:
            response = requests.post(
                f"{NAMING_SERVICE_URL}/api/upload/confirm",
                json={
                    "file_id": file_id,
                    "node_id": self.node_id,
                    "checksum": checksum
                },
                timeout=5
            )
            
            return response.status_code == 200
            
        except Exception as e:
            print(f"⚠️  Confirm upload error: {e}")
            return False

# Initialize storage node
storage_node = None

# === API Endpoints ===

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    used_space = storage_node.get_used_space()
    available_space = storage_node.get_available_space()
    max_storage = storage_node.max_storage
    
    return jsonify({
        "status": "healthy",
        "node_id": storage_node.node_id,
        "available_space": available_space,
        "used_space": used_space,
        "max_storage": max_storage,
        "file_count": storage_node.get_file_count(),
        "storage_percentage": (used_space / max_storage * 100) if max_storage else 0
    })

@app.route('/upload/<file_id>', methods=['POST'])
def upload_file(file_id):
    """Upload file endpoint"""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    try:
        # Read file data
        file_data = file.read()
        file_size = len(file_data)
        
        # Cek apakah ada cukup space
        available = storage_node.get_available_space()
        if file_size > available:
            used = storage_node.get_used_space()
            max_storage = storage_node.max_storage or "unlimited"
            return jsonify({
                "error": "Insufficient storage space",
                "message": f"Node {storage_node.node_id} tidak memiliki cukup space",
                "file_size_mb": file_size / (1024**2),
                "available_mb": available / (1024**2),
                "used_mb": used / (1024**2),
                "max_storage_mb": max_storage / (1024**2) if isinstance(max_storage, int) else max_storage
            }), 507
        
        # Save file with metadata
        result = storage_node.save_file(file_id, file_data, filename=file.filename)
        
        # Confirm upload ke naming service
        storage_node.confirm_upload(file_id, result["checksum"])
        
        print(f"✅ File uploaded: {file_id} ({result['size']} bytes) - Original: {file.filename}")
        
        return jsonify({
            "status": "success",
            "file_id": file_id,
            "checksum": result["checksum"],
            "size": result["size"]
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/download/<file_id>', methods=['GET'])
def download_file(file_id):
    """Download file endpoint"""
    filepath = storage_node.get_file(file_id)
    
    if not filepath:
        return jsonify({"error": "File not found"}), 404
    
    # Get original filename from metadata
    original_filename = storage_node.get_file_metadata(file_id)
    if not original_filename:
        original_filename = file_id  # Fallback to file_id jika metadata tidak ada
    
    print(f"📥 File downloaded: {file_id} ({original_filename})")
    
    return send_file(filepath, as_attachment=True, download_name=original_filename)

@app.route('/delete/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete file endpoint"""
    success = storage_node.delete_file(file_id)
    
    if success:
        print(f"🗑️  File deleted: {file_id}")
        return jsonify({"status": "success"})
    else:
        return jsonify({"error": "File not found"}), 404

@app.route('/verify/<file_id>', methods=['GET'])
def verify_file(file_id):
    """Verify file exists and return checksum"""
    filepath = storage_node.get_file(file_id)
    
    if not filepath:
        return jsonify({"error": "File not found"}), 404
    
    checksum = storage_node.calculate_checksum(filepath)
    size = os.path.getsize(filepath)
    
    return jsonify({
        "file_id": file_id,
        "checksum": checksum,
        "size": size,
        "exists": True
    })

@app.route('/stats', methods=['GET'])
def stats():
    """Storage statistics"""
    return jsonify({
        "node_id": storage_node.node_id,
        "storage_dir": storage_node.storage_dir,
        "available_space": storage_node.get_available_space(),
        "file_count": storage_node.get_file_count()
    })

def heartbeat_loop():
    """Background thread untuk kirim heartbeat"""
    # Wait untuk register dulu
    time.sleep(2)
    
    while True:
        storage_node.send_heartbeat()
        time.sleep(10)  # Send heartbeat every 10 seconds

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Storage Node Server')
    parser.add_argument('--port', type=int, required=True, help='Port untuk storage node')
    parser.add_argument('--storage-dir', type=str, required=True, help='Directory untuk storage')
    parser.add_argument('--node-id', type=str, default=None, help='Node ID (default: node-{port})')
    
    args = parser.parse_args()
    
    # Set configuration
    NODE_ID = args.node_id or f"node-{args.port}"
    STORAGE_DIR = args.storage_dir
    
    # Initialize storage node
    storage_node = StorageNode(NODE_ID, STORAGE_DIR)
    
    # Register with naming service
    node_address = f"http://localhost:{args.port}"
    storage_node.register_with_naming_service(node_address)
    
    # Start heartbeat thread
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    
    print("=" * 60)
    print(f"🗄️  Distributed File System - Storage Node")
    print("=" * 60)
    print(f"📍 Node ID: {NODE_ID}")
    print(f"📁 Storage Dir: {STORAGE_DIR}")
    print(f"🌐 Address: {node_address}")
    print(f"📊 Endpoints:")
    print(f"   - POST /upload/<file_id>")
    print(f"   - GET  /download/<file_id>")
    print(f"   - DELETE /delete/<file_id>")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=args.port, debug=False)
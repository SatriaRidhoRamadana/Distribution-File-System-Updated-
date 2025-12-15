"""
Distributed File System - Naming Service (Database Version)
Mengelola metadata file dan koordinasi antar storage nodes
"""

from flask import Flask, request, jsonify, render_template_string, redirect
from flask_cors import CORS
from werkzeug.exceptions import RequestEntityTooLarge
import uuid
import threading
import time
from datetime import datetime
import requests
import sys
import os
import re

# Import database
sys.path.append(os.path.dirname(__file__))
from database_schema import DFSDatabase

app = Flask(__name__)
CORS(app)

# File size limit (100 MB)
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB in bytes
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE

# Error handlers for consistent JSON responses
@app.errorhandler(RequestEntityTooLarge)
def handle_request_entity_too_large(err):
    max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
    return jsonify({
        "error": "File too large",
        "message": f"Ukuran file melebihi batas {max_size_mb:.0f} MB",
        "status": "size_limit_exceeded"
    }), 413

@app.errorhandler(500)
def handle_internal_error(err):
    return jsonify({
        "error": "Internal server error",
        "message": "Terjadi kesalahan di server. Coba ulangi atau cek log server.",
        "status": "internal_error"
    }), 500

# Storage node capacity limit for testing (10 MB per node)
# Set to None for unlimited storage
MAX_STORAGE_PER_NODE = None  #10 * 1024 * 1024 for storage full test
# Buffer space (in bytes) required beyond file size; set 0 if not used
MIN_SPACE_BUFFER = 0  # previously None caused TypeError

# Initialize database
db = DFSDatabase("dfs.db")

class NamingService:
    def __init__(self):
        self.lock = threading.Lock()
        self.last_recovery_check = {}  # Track last recovery check per node
    
    def select_nodes_for_upload(self, replication_factor=2, file_size=0):
        """Pilih node untuk upload file dengan validasi kapasitas"""
        active_nodes = db.get_active_nodes()
        
        if len(active_nodes) < replication_factor:
            return None
        
        # Filter nodes dengan space cukup untuk file + buffer
        buffer_bytes = MIN_SPACE_BUFFER or 0
        required_space = file_size + buffer_bytes
        required_space_mb = required_space / (1024**2)
        file_size_mb = file_size / (1024**2)
        nodes_with_space = [
            node for node in active_nodes 
            if node['available_space'] >= required_space
        ]
        
        if len(nodes_with_space) < replication_factor:
            # Return info tentang nodes yang tersedia
            return {
                "status": "insufficient_space",
                "available_nodes": len(nodes_with_space),
                "required_nodes": replication_factor,
                "nodes_info": [
                    {
                        "node_id": node['node_id'],
                        "available_space_mb": node['available_space'] / (1024**2),
                        "required_space_mb": required_space_mb,
                        "file_size_mb": file_size_mb,
                        "buffer_mb": buffer_bytes / (1024**2),
                        "deficit_mb": max(required_space - node['available_space'], 0) / (1024**2)
                    }
                    for node in active_nodes[:5]  # Show top 5 nodes
                ]
            }
        
        # Return top N nodes berdasarkan available space
        return nodes_with_space[:replication_factor]
    
    def handle_node_recovery(self, node_id):
        """Handle ketika node aktif kembali - trigger auto-replication untuk load balancing"""
        print(f"\n[RECOVERY] Handling recovery for {node_id}")
        
        try:
            # Get node address
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT node_address FROM storage_nodes WHERE node_id = ?", (node_id,))
                row = cursor.fetchone()
                if not row:
                    print(f"   Node {node_id} not found in database")
                    return
                node_address = row['node_address']
            
            print(f"   Node address: {node_address}")
            
            # Strategy 1: Check files yang sudah punya replica record di node ini tapi filenya hilang
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT f.file_id, f.filename, f.file_size, f.replication_factor
                    FROM files f
                    INNER JOIN replicas r ON f.file_id = r.file_id
                    WHERE r.node_id = ?
                    LIMIT 100
                """, (node_id,))
                
                existing_replica_files = [dict(row) for row in cursor.fetchall()]
            
            recovered_count = 0
            
            if existing_replica_files:
                print(f"   Checking {len(existing_replica_files)} files with existing replicas...")
                
                for file_info in existing_replica_files:
                    file_id = file_info['file_id']
                    filename = file_info['filename']
                    
                    try:
                        verify_url = f"{node_address}/verify/{file_id}"
                        verify_response = requests.get(verify_url, timeout=15)
                        
                        if verify_response.status_code == 200:
                            db.update_replica_status(file_id, node_id, 'active')
                            print(f"   OK: {filename}")
                        else:
                            # Need to recover
                            print(f"   RECOVER: {filename}...")
                            recovered_count += self._recover_file_to_node(file_id, filename, node_id, node_address, update_only=True)
                    except:
                        print(f"   RECOVER: {filename}...")
                        recovered_count += self._recover_file_to_node(file_id, filename, node_id, node_address, update_only=True)
            
            # Strategy 2: Redistribute ALL files untuk load balancing
            # Get all active nodes
            active_nodes = db.get_active_nodes()
            active_node_ids = [n['node_id'] for n in active_nodes]
            
            print(f"   Active nodes: {len(active_nodes)} - redistributing files for load balancing...")
            
            # Get all files
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT DISTINCT f.file_id, f.filename, f.file_size, f.replication_factor
                    FROM files f
                    LIMIT 100
                """)
                
                all_files = [dict(row) for row in cursor.fetchall()]
            
            if not all_files:
                print(f"   No files to redistribute")
            else:
                print(f"   Checking {len(all_files)} files for redistribution...")
                
                for file_info in all_files:
                    file_id = file_info['file_id']
                    filename = file_info['filename']
                    replication_factor = file_info['replication_factor']
                    
                    # Get current active replicas for this file
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT node_id FROM replicas 
                            WHERE file_id = ? AND status = 'active'
                        """, (file_id,))
                        current_replica_nodes = [row['node_id'] for row in cursor.fetchall()]
                    
                    # Check if this node should have this file
                    # Strategy: distribute evenly across all nodes up to replication_factor
                    # If this node doesn't have it yet, add it
                    if node_id not in current_replica_nodes:
                        # Only replicate if current count < replication_factor OR for load balancing
                        # We want to spread files across all available nodes
                        if len(current_replica_nodes) < len(active_node_ids):
                            # Check if node already processed in strategy 1
                            with db.get_connection() as conn:
                                cursor = conn.cursor()
                                cursor.execute("""
                                    SELECT * FROM replicas 
                                    WHERE file_id = ? AND node_id = ?
                                """, (file_id, node_id))
                                existing_replica = cursor.fetchone()
                            
                            if existing_replica:
                                # Already handled in strategy 1
                                continue
                            
                            # Replicate to this node for better distribution
                            print(f"   DISTRIBUTE: {filename}...")
                            result = self._recover_file_to_node(file_id, filename, node_id, node_address, update_only=False)
                            recovered_count += result
                            
                            # Small delay to avoid overwhelming the node
                            if result > 0:
                                time.sleep(0.1)
            
            print(f"   Recovery complete: {recovered_count} files recovered/redistributed")
            
        except Exception as e:
            print(f"   FATAL ERROR: {str(e)}")
    
    def _recover_file_to_node(self, file_id, filename, target_node_id, target_node_address, update_only=False):
        """Helper function to recover/replicate a file to a target node"""
        try:
            # Find active replica to copy from
            file_replicas = db.get_file(file_id)
            if not file_replicas:
                print(f"      File {file_id} not in database")
                return 0
            
            source_replica = None
            for replica in file_replicas.get('replicas', []):
                if replica['status'] == 'active' and replica['node_id'] != target_node_id:
                    source_replica = replica
                    break
            
            if not source_replica:
                print(f"      No active source found")
                return 0
            
            # Download file dari source node
            download_url = f"{source_replica['node_address']}/download/{file_id}"
            
            download_response = requests.get(download_url, timeout=30, stream=True)
            if download_response.status_code != 200:
                print(f"      Download failed: {download_response.status_code}")
                return 0
            
            # Upload ke target node
            upload_url = f"{target_node_address}/upload/{file_id}"
            file_content = download_response.content
            
            files = {'file': (filename, file_content)}
            upload_response = requests.post(upload_url, files=files, timeout=30)
            
            if upload_response.status_code == 200:
                # Add or update replica record
                if update_only:
                    db.update_replica_status(file_id, target_node_id, 'active')
                else:
                    # Check if replica exists
                    with db.get_connection() as conn:
                        cursor = conn.cursor()
                        cursor.execute("""
                            SELECT * FROM replicas 
                            WHERE file_id = ? AND node_id = ?
                        """, (file_id, target_node_id))
                        existing = cursor.fetchone()
                        
                        if existing:
                            db.update_replica_status(file_id, target_node_id, 'active')
                        else:
                            db.add_replica(file_id, target_node_id, target_node_address)
                
                print(f"      COPIED from {source_replica['node_id']}")
                return 1
            else:
                print(f"      Upload failed: {upload_response.status_code}")
                return 0
                
        except requests.exceptions.Timeout:
            print(f"      TIMEOUT")
            return 0
        except requests.exceptions.RequestException as e:
            print(f"      ERROR: {str(e)[:50]}")
            return 0
        except Exception as e:
            print(f"      ERROR: {type(e).__name__}")
            return 0

naming_service = NamingService()

# === API Endpoints ===

@app.route('/')
def index():
    """Web UI Dashboard"""
    return render_template_string(WEB_UI_TEMPLATE)

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "service": "naming-service",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/nodes/register', methods=['POST'])
def register_node():
    """Register storage node"""
    data = request.json
    node_id = data.get('node_id')
    node_address = data.get('node_address')
    
    if not node_id or not node_address:
        return jsonify({"error": "node_id dan node_address required"}), 400
    
    # Check if node was previously inactive (re-registration after restart)
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM storage_nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        was_inactive = row and row['status'] == 'inactive'
    
    # Register/update node
    db.register_node(node_id, node_address)
    
    # Trigger recovery jika node sebelumnya inactive
    if was_inactive:
        print(f"\n🔔 [RECOVERY DETECTED] {node_id} re-registered after being offline!")
        recovery_thread = threading.Thread(
            target=naming_service.handle_node_recovery,
            args=(node_id,),
            daemon=True
        )
        recovery_thread.start()
    
    return jsonify({
        "status": "success",
        "message": f"Node {node_id} registered"
    })

@app.route('/api/nodes/heartbeat', methods=['POST'])
def heartbeat():
    """Heartbeat dari storage node"""
    data = request.json
    node_id = data.get('node_id')
    available_space = data.get('available_space', 0)
    file_count = data.get('file_count', 0)
    
    if not node_id:
        return jsonify({"error": "node_id required"}), 400
    
    # Get current node status sebelum update
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM storage_nodes WHERE node_id = ?", (node_id,))
        row = cursor.fetchone()
        previous_status = row['status'] if row else None
    
    # Update heartbeat
    success = db.update_node_heartbeat(node_id, available_space, file_count)
    
    if success:
        # Check if node baru aktif (was inactive, now active)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status FROM storage_nodes WHERE node_id = ?", (node_id,))
            row = cursor.fetchone()
            current_status = row['status'] if row else None
        
        # Trigger recovery jika node baru aktif kembali
        if previous_status == 'inactive' and current_status == 'active':
            print(f"\n🔔 [RECOVERY DETECTED] {node_id} is back online!")
            # Trigger auto-replication di background thread
            recovery_thread = threading.Thread(
                target=naming_service.handle_node_recovery,
                args=(node_id,),
                daemon=True
            )
            recovery_thread.start()
        
        return jsonify({"status": "success"})
    else:
        return jsonify({"error": "Node not found"}), 404

@app.route('/api/nodes', methods=['GET'])
def list_nodes():
    """List semua storage nodes"""
    nodes = db.get_all_nodes()
    return jsonify({"nodes": nodes})

@app.route('/api/upload/request', methods=['POST'])
def upload_request():
    """Request untuk upload file"""
    data = request.json
    filename = data.get('filename')
    file_size = data.get('file_size')
    replication_factor = data.get('replication_factor', 2)
    
    if not filename or not file_size:
        return jsonify({"error": "filename dan file_size required"}), 400
    
    # Validasi ukuran file - maksimal 100 MB
    if file_size > MAX_FILE_SIZE:
        max_size_mb = MAX_FILE_SIZE / (1024 * 1024)
        file_size_mb = file_size / (1024 * 1024)
        return jsonify({
            "error": f"Ukuran file melampaui batas maksimum {max_size_mb:.0f} MB",
            "message": f"File '{filename}' berukuran {file_size_mb:.2f} MB, maksimal yang diperbolehkan adalah {max_size_mb:.0f} MB",
            "max_size_mb": max_size_mb,
            "file_size_mb": file_size_mb,
            "status": "size_limit_exceeded"
        }), 413
    
    # Pilih nodes untuk upload dengan validasi kapasitas
    selected_nodes = naming_service.select_nodes_for_upload(replication_factor, file_size)
    active_count = len(db.get_active_nodes())
    
    # Cek apakah result adalah dict (error) atau list (success)
    if isinstance(selected_nodes, dict):
        # Storage nodes penuh atau tidak cukup space
        file_size_mb = file_size / (1024 * 1024)
        required_space_mb = (file_size + MIN_SPACE_BUFFER) / (1024 * 1024)
        return jsonify({
            "error": "Storage nodes tidak memiliki cukup space",
            "message": f"Tidak ada {replication_factor} node dengan space cukup untuk file '{filename}' ({file_size_mb:.2f} MB). Dibutuhkan {required_space_mb:.2f} MB termasuk buffer.",
            "file_size_mb": file_size_mb,
            "required_space_mb": required_space_mb,
            "required_nodes": replication_factor,
            "available_nodes_with_space": selected_nodes.get('available_nodes', 0),
            "nodes_info": selected_nodes.get('nodes_info', []),
            "status": "storage_full"
        }), 507
    
    if not selected_nodes or len(selected_nodes) < replication_factor:
        return jsonify({
            "error": f"Tidak cukup storage nodes aktif. Butuh {replication_factor} nodes, hanya tersedia {active_count} nodes.",
            "required": replication_factor,
            "available": active_count
        }), 503
    
    # Buat file record
    file_id = str(uuid.uuid4())
    db.create_file(file_id, filename, file_size, replication_factor)
    
    # Buat replica records
    upload_nodes = []
    for node in selected_nodes:
        db.add_replica(file_id, node["node_id"], node["node_address"])
        upload_nodes.append({
            "node_id": node["node_id"],
            "upload_url": f"{node['node_address']}/upload/{file_id}"
        })
    
    return jsonify({
        "status": "success",
        "file_id": file_id,
        "upload_nodes": upload_nodes
    })

@app.route('/api/upload/confirm', methods=['POST'])
def upload_confirm():
    """Konfirmasi upload berhasil"""
    data = request.json
    file_id = data.get('file_id')
    node_id = data.get('node_id')
    checksum = data.get('checksum')
    
    if not all([file_id, node_id, checksum]):
        return jsonify({"error": "file_id, node_id, checksum required"}), 400
    
    # Update replica status
    db.update_replica_status(file_id, node_id, 'active')
    
    return jsonify({"status": "success"})

@app.route('/api/upload/cancel', methods=['POST'])
def upload_cancel():
    """Cancel upload dan cleanup file record jika upload gagal"""
    data = request.json
    file_id = data.get('file_id')
    reason = data.get('reason', 'Unknown')
    
    if not file_id:
        return jsonify({"error": "file_id required"}), 400
    
    print(f"\n[UPLOAD CANCEL] File {file_id} - Reason: {reason}")
    
    # Delete file dan replicas dari database
    with db.get_connection() as conn:
        cursor = conn.cursor()
        
        # Get file info untuk logging
        cursor.execute("SELECT filename FROM files WHERE file_id = ?", (file_id,))
        row = cursor.fetchone()
        filename = row['filename'] if row else 'unknown'
        
        # Delete replicas
        cursor.execute("DELETE FROM replicas WHERE file_id = ?", (file_id,))
        deleted_replicas = cursor.rowcount
        
        # Delete file
        cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
        
        conn.commit()
        
        print(f"   Cleaned up: {filename} (removed {deleted_replicas} replica records)")
    
    return jsonify({
        "status": "success",
        "message": f"Upload cancelled and cleaned up for {filename}"
    })
    
    # Update file checksum if not set
    file_info = db.get_file(file_id)
    if file_info and not file_info['checksum']:
        db.update_file_checksum(file_id, checksum)
    
    return jsonify({"status": "success"})

@app.route('/api/download/<file_id>', methods=['GET'])
def download_request(file_id):
    """Request untuk download file"""
    file_info = db.get_file(file_id)
    
    if not file_info:
        return jsonify({"error": "File tidak ditemukan"}), 404
    
    # Get active nodes
    active_nodes = db.get_active_nodes()
    active_node_ids = [node['node_id'] for node in active_nodes]
    
    # Get replicas dari node yang aktif
    active_replicas = [
        replica for replica in file_info["replicas"]
        if replica["status"] == "active" and replica["node_id"] in active_node_ids
    ]
    
    if not active_replicas:
        return jsonify({"error": "Tidak ada replica aktif"}), 503
    
    download_urls = [
        f"{replica['node_address']}/download/{file_id}"
        for replica in active_replicas
    ]
    
    return jsonify({
        "file_id": file_id,
        "filename": file_info["filename"],
        "file_size": file_info["file_size"],
        "checksum": file_info["checksum"],
        "download_urls": download_urls
    })

@app.route('/download/<file_id>', methods=['GET'])
def download_file_proxy(file_id):
    """Proxy download endpoint - handle localhost redirection"""
    file_info = db.get_file(file_id)
    
    if not file_info:
        return jsonify({"error": "File tidak ditemukan"}), 404
    
    # Get active nodes
    active_nodes = db.get_active_nodes()
    active_node_ids = [node['node_id'] for node in active_nodes]
    
    # Get replicas dari node yang aktif
    active_replicas = [
        replica for replica in file_info["replicas"]
        if replica["status"] == "active" and replica["node_id"] in active_node_ids
    ]
    
    if not active_replicas:
        return jsonify({"error": "Tidak ada replica aktif"}), 503
    
    # Use first active replica, extract port and use localhost
    replica = active_replicas[0]
    node_address = replica['node_address']
    
    # Extract port from node_address (e.g., "http://192.168.1.100:5001" -> "5001")
    match = re.search(r':(\d+)$', node_address)
    if match:
        port = match.group(1)
        node_address = f"http://localhost:{port}"
    
    # Redirect to localhost download URL
    download_url = f"{node_address}/download/{file_id}?download_name={file_info['filename']}"
    return redirect(download_url)


@app.route('/api/files', methods=['GET'])
def list_files():
    """List semua file dengan pagination"""
    limit = int(request.args.get('limit', 100))
    offset = int(request.args.get('offset', 0))
    
    result = db.list_files(limit, offset)
    return jsonify(result)

@app.route('/api/files/<file_id>', methods=['GET'])
def get_file(file_id):
    """Get file detail"""
    file_info = db.get_file(file_id)
    
    if not file_info:
        return jsonify({"error": "File tidak ditemukan"}), 404
    
    return jsonify(file_info)

@app.route('/api/files/<file_id>', methods=['DELETE'])
def delete_file(file_id):
    """Delete file"""
    file_info = db.get_file(file_id)
    
    if not file_info:
        return jsonify({"error": "File tidak ditemukan"}), 404
    
    # Kirim delete request ke semua replicas
    for replica in file_info["replicas"]:
        try:
            requests.delete(
                f"{replica['node_address']}/delete/{file_id}",
                timeout=5
            )
        except:
            pass
    
    # Hapus dari database
    db.delete_file(file_id)
    
    return jsonify({"status": "success"})

@app.route('/api/files/delete-all', methods=['POST'])
def delete_all_files():
    """Delete semua file dari sistem"""
    # Get all files from database
    result = db.list_files(limit=1000, offset=0)
    files = result['files']
    deleted_count = 0
    
    for file in files:
        file_id = file["file_id"]
        
        # Get file info with replicas
        file_info = db.get_file(file_id)
        
        if file_info:
            # Delete from all replicas
            for replica in file_info["replicas"]:
                try:
                    requests.delete(
                        f"{replica['node_address']}/delete/{file_id}",
                        timeout=5
                    )
                except:
                    pass
        
        # Delete from database
        db.delete_file(file_id)
        deleted_count += 1
    
    return jsonify({
        "status": "success",
        "deleted_count": deleted_count
    })

@app.route('/api/stats', methods=['GET'])
def stats():
    """Statistik sistem"""
    stats = db.get_stats()
    
    return jsonify({
        "total_nodes": stats['total_nodes'],
        "active_nodes": stats['active_nodes'],
        "total_files": stats['total_files'],
        "total_size_bytes": stats['total_size'],
        "total_size_mb": round(stats['total_size'] / (1024 * 1024), 2),
        "recent_uploads": stats['recent_uploads']
    })

@app.route('/api/history', methods=['GET'])
def history():
    """Upload history"""
    limit = int(request.args.get('limit', 50))
    history = db.get_upload_history(limit)
    return jsonify({"history": history})

def health_check_loop():
    """Background thread untuk cek health nodes"""
    while True:
        time.sleep(30)
        active_nodes = db.get_active_nodes()
        
        # Cleanup orphaned files (files dengan 0 active replicas)
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.file_id, f.filename, 
                       COUNT(CASE WHEN r.status = 'active' THEN 1 END) as active_count
                FROM files f
                LEFT JOIN replicas r ON f.file_id = r.file_id
                GROUP BY f.file_id
                HAVING active_count = 0
            """)
            orphaned_files = cursor.fetchall()
            
            if orphaned_files:
                print(f"[CLEANUP] Found {len(orphaned_files)} orphaned file(s) with 0 replicas")
                for file_row in orphaned_files:
                    file_id = file_row['file_id']
                    filename = file_row['filename']
                    print(f"   Removing orphaned file: {filename} ({file_id})")
                    
                    # Delete replicas
                    cursor.execute("DELETE FROM replicas WHERE file_id = ?", (file_id,))
                    # Delete file
                    cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                
                conn.commit()
        
        print("[HEALTH CHECK] Scanning all active nodes for missing files...")
        for node in active_nodes:
            node_id = node['node_id']
            node_address = node['node_address']
            # Get all files that should be on this node
            with db.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT f.file_id, f.filename
                    FROM files f
                    INNER JOIN replicas r ON f.file_id = r.file_id
                    WHERE r.node_id = ?
                """, (node_id,))
                files = [dict(row) for row in cursor.fetchall()]
            for file in files:
                file_id = file['file_id']
                filename = file['filename']
                try:
                    verify_url = f"{node_address}/verify/{file_id}"
                    verify_response = requests.get(verify_url, timeout=10)
                    if verify_response.status_code == 200:
                        # File exists, mark as active
                        db.update_replica_status(file_id, node_id, 'active')
                    else:
                        print(f"[HEALTH CHECK] File missing: {filename} on {node_id}, triggering recovery...")
                        # Recover file to this node
                        naming_service._recover_file_to_node(file_id, filename, node_id, node_address, update_only=True)
                except Exception as e:
                    print(f"[HEALTH CHECK] Error verifying {filename} on {node_id}: {str(e)}")

# Web UI Template
WEB_UI_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DFS - Distributed File System</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        .header {
            background: white;
            padding: 30px;
            border-radius: 15px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.2);
            margin-bottom: 30px;
        }
        .header h1 {
            color: #667eea;
            font-size: 2.5em;
            margin-bottom: 10px;
        }
        .header p {
            color: #666;
            font-size: 1.1em;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
            text-align: center;
            transition: transform 0.3s ease;
        }
        .stat-card:hover {
            transform: translateY(-5px);
        }
        .stat-card .number {
            font-size: 3em;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }
        .stat-card .label {
            color: #666;
            font-size: 1.1em;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .content-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .panel {
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 5px 15px rgba(0,0,0,0.1);
        }
        .panel h2 {
            color: #667eea;
            margin-bottom: 20px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
        }
        .upload-form {
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .form-group label {
            font-weight: 600;
            color: #333;
        }
        .form-group input[type="file"],
        .form-group input[type="number"] {
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 1em;
        }
        .btn {
            padding: 15px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 1.1em;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .btn:hover {
            transform: scale(1.05);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
            transform: none;
        }
        .file-list, .node-list {
            max-height: 400px;
            overflow-y: auto;
        }
        .file-item, .node-item {
            padding: 15px;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 10px;
            transition: all 0.3s ease;
        }
        .file-item:hover, .node-item:hover {
            background: #f8f9ff;
            border-color: #667eea;
        }
        .file-item h3, .node-item h3 {
            color: #333;
            font-size: 1.1em;
            margin-bottom: 8px;
        }
        .file-item p, .node-item p {
            color: #666;
            font-size: 0.9em;
            margin: 4px 0;
        }
        .status {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 0.85em;
            font-weight: 600;
        }
        .status.active {
            background: #d4edda;
            color: #155724;
        }
        .status.inactive {
            background: #f8d7da;
            color: #721c24;
        }
        .file-actions {
            margin-top: 10px;
            display: flex;
            gap: 10px;
        }
        .btn-small {
            padding: 8px 16px;
            font-size: 0.9em;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .btn-small:hover {
            background: #5568d3;
        }
        .btn-small.danger {
            background: #dc3545;
        }
        .btn-small.danger:hover {
            background: #c82333;
        }
        .alert {
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert.success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        .alert.error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        .progress {
            width: 100%;
            height: 30px;
            background: #e0e0e0;
            border-radius: 15px;
            overflow: hidden;
            margin: 15px 0;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
            transition: width 0.3s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
        }
        @media (max-width: 768px) {
            .content-grid {
                grid-template-columns: 1fr;
            }
            .stats-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🗄️ Distributed File System</h1>
            <p>Manage your distributed file storage with ease</p>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">Total Files</div>
                <div class="number" id="totalFiles">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Active Nodes</div>
                <div class="number" id="activeNodes">0</div>
            </div>
            <div class="stat-card">
                <div class="label">Total Storage</div>
                <div class="number" id="totalStorage">0 MB</div>
            </div>
            <div class="stat-card">
                <div class="label">Recent Uploads</div>
                <div class="number" id="recentUploads">0</div>
            </div>
        </div>

        <div class="content-grid">
            <div class="panel">
                <h2>📤 Upload File</h2>
                <div id="uploadAlert"></div>
                <form class="upload-form" id="uploadForm">
                    <div class="form-group">
                        <label>Select File</label>
                        <input type="file" id="fileInput" required>
                    </div>
                    <div class="form-group">
                        <label>Replication Factor</label>
                        <input type="number" id="replicationFactor" min="2" max="5" value="2">
                    </div>
                    <div id="uploadProgress" style="display: none;">
                        <div class="progress">
                            <div class="progress-bar" id="progressBar">0%</div>
                        </div>
                    </div>
                    <button type="submit" class="btn" id="uploadBtn">Upload File</button>
                </form>
            </div>

            <div class="panel">
                <h2>🗄️ Storage Nodes</h2>
                <div class="node-list" id="nodeList">
                    <p style="text-align: center; color: #999;">Loading...</p>
                </div>
            </div>
        </div>

        <div class="panel" style="margin-top: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h2 style="margin: 0;">📂 Files</h2>
                <button class="btn danger" onclick="deleteAllFiles()" style="padding: 8px 16px;">🗑️ Delete All</button>
            </div>
            <div class="file-list" id="fileList">
                <p style="text-align: center; color: #999;">Loading...</p>
            </div>
        </div>
    </div>

    <script>
        const API_BASE = window.location.origin;

        // Load stats
        async function loadStats() {
            try {
                const res = await fetch(`${API_BASE}/api/stats`);
                const data = await res.json();
                
                document.getElementById('totalFiles').textContent = data.total_files;
                document.getElementById('activeNodes').textContent = data.active_nodes;
                document.getElementById('totalStorage').textContent = data.total_size_mb + ' MB';
                document.getElementById('recentUploads').textContent = data.recent_uploads;
            } catch (err) {
                console.error('Error loading stats:', err);
            }
        }

        // Load nodes
        async function loadNodes() {
            try {
                const res = await fetch(`${API_BASE}/api/nodes`);
                const data = await res.json();
                
                const nodeList = document.getElementById('nodeList');
                
                if (data.nodes.length === 0) {
                    nodeList.innerHTML = '<p style="text-align: center; color: #999;">No nodes registered</p>';
                    return;
                }
                
                nodeList.innerHTML = data.nodes.map(node => `
                    <div class="node-item">
                        <h3>${node.node_id}</h3>
                        <p>Address: ${node.node_address}</p>
                        <p>Status: <span class="status ${node.status}">${node.status}</span></p>
                        <p>Files: ${node.total_files} | Space: ${(node.available_space / (1024**3)).toFixed(2)} GB</p>
                        <p style="font-size: 0.8em; color: #999;">Last seen: ${new Date(node.last_heartbeat).toLocaleString()}</p>
                    </div>
                `).join('');
            } catch (err) {
                console.error('Error loading nodes:', err);
            }
        }

        // Load files
        async function loadFiles() {
            try {
                const res = await fetch(`${API_BASE}/api/files`);
                const data = await res.json();
                
                const fileList = document.getElementById('fileList');
                
                if (data.files.length === 0) {
                    fileList.innerHTML = '<p style="text-align: center; color: #999;">No files uploaded</p>';
                    return;
                }
                
                fileList.innerHTML = data.files.map(file => `
                    <div class="file-item">
                        <h3>${file.filename}</h3>
                        <p>File ID: ${file.file_id}</p>
                        <p>Size: ${(file.file_size / (1024**2)).toFixed(2)} MB | Replicas: ${file.active_replicas}/${file.replica_count}</p>
                        <p style="font-size: 0.8em; color: #999;">Uploaded: ${new Date(file.upload_timestamp).toLocaleString()}</p>
                        <div class="file-actions">
                            <button class="btn-small" onclick="downloadFile('${file.file_id}')">Download</button>
                            <button class="btn-small danger" onclick="deleteFile('${file.file_id}')">Delete</button>
                        </div>
                    </div>
                `).join('');
            } catch (err) {
                console.error('Error loading files:', err);
            }
        }

        // Upload file
        document.getElementById('uploadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const fileInput = document.getElementById('fileInput');
            const replicationFactor = document.getElementById('replicationFactor').value;
            const file = fileInput.files[0];
            
            if (!file) return;
            
            const uploadBtn = document.getElementById('uploadBtn');
            const uploadProgress = document.getElementById('uploadProgress');
            const progressBar = document.getElementById('progressBar');
            const uploadAlert = document.getElementById('uploadAlert');
            
            // Validasi ukuran file - maksimal 100 MB
            const MAX_FILE_SIZE = 100 * 1024 * 1024; // 100 MB
            if (file.size > MAX_FILE_SIZE) {
                const fileSizeMB = (file.size / (1024 * 1024)).toFixed(2);
                const maxSizeMB = MAX_FILE_SIZE / (1024 * 1024);
                uploadAlert.innerHTML = `<div class="alert error">⚠️ <strong>File Terlalu Besar!</strong><br/>File '${file.name}' berukuran ${fileSizeMB} MB, maksimal yang diperbolehkan hanya ${maxSizeMB} MB</div>`;
                return;
            }
            
            uploadBtn.disabled = true;
            uploadProgress.style.display = 'block';
            progressBar.style.width = '0%';
            progressBar.textContent = '0%';
            uploadAlert.innerHTML = '';
            
            try {
                // Step 1: Request upload
                progressBar.style.width = '20%';
                progressBar.textContent = '20%';
                
                const reqRes = await fetch(`${API_BASE}/api/upload/request`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        filename: file.name,
                        file_size: file.size,
                        replication_factor: parseInt(replicationFactor)
                    })
                });
                
                if (!reqRes.ok) {
                    let errorData = {};
                    let text = '';
                    try {
                        errorData = await reqRes.json();
                    } catch (jsonErr) {
                        text = await reqRes.text();
                    }
                    // Cek apakah error karena ukuran file
                    if (errorData.status === 'size_limit_exceeded') {
                        throw new Error(`📦 ${errorData.message}`);
                    }
                    // Cek apakah error karena storage penuh
                    if (errorData.status === 'storage_full') {
                        let errorMsg = `💾 <strong>Storage Penuh!</strong><br/>${errorData.message}<br/><br/>`;
                        errorMsg += `<strong>Detail Nodes:</strong><br/>`;
                        if (errorData.nodes_info && errorData.nodes_info.length > 0) {
                            errorData.nodes_info.forEach(node => {
                                const deficit = node.deficit_mb !== undefined ? node.deficit_mb : (node.required_space_mb - node.available_space_mb);
                                errorMsg += `• ${node.node_id}: ${node.available_space_mb.toFixed(2)} MB available (need ${node.required_space_mb.toFixed(2)} MB incl. buffer ${node.buffer_mb?.toFixed(2) ?? 'N/A'} MB, deficit ${deficit.toFixed(2)} MB)<br/>`;
                            });
                        }
                        uploadAlert.innerHTML = `<div class="alert error">${errorMsg}</div>`;
                        throw new Error('Storage full');
                    }
                    const msg = errorData.error || errorData.message || text || 'Upload request failed';
                    throw new Error(msg);
                }
                
                const reqData = await reqRes.json();
                
                // Validasi upload nodes tersedia
                if (!reqData.upload_nodes || reqData.upload_nodes.length === 0) {
                    throw new Error('No storage nodes available for upload');
                }
                
                // Step 2: Upload to nodes
                progressBar.style.width = '50%';
                progressBar.textContent = '50%';
                
                const uploadPromises = reqData.upload_nodes.map(node => {
                    const formData = new FormData();
                    formData.append('file', file);
                    return fetch(node.upload_url, {
                        method: 'POST',
                        body: formData
                    });
                });
                
                const uploadResults = await Promise.all(uploadPromises);
                
                // Validasi semua upload berhasil
                const failedUploads = uploadResults.filter(res => !res.ok);
                if (failedUploads.length > 0) {
                    // Cancel upload dan cleanup database
                    try {
                        await fetch(`${API_BASE}/api/upload/cancel`, {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                file_id: reqData.file_id,
                                reason: `Upload failed to ${failedUploads.length} node(s)`
                            })
                        });
                    } catch (cancelErr) {
                        console.error('Failed to cancel upload:', cancelErr);
                    }
                    throw new Error(`Upload failed to ${failedUploads.length} node(s)`);
                }
                
                progressBar.style.width = '100%';
                progressBar.textContent = '100%';
                
                uploadAlert.innerHTML = '<div class="alert success">✅ File uploaded successfully!</div>';
                
                // Reset form
                fileInput.value = '';
                
                // Refresh data
                loadStats();
                loadFiles();
                
            } catch (err) {
                // Jangan tampilkan alert jika sudah ditampilkan di uploadAlert (untuk storage_full)
                if (err.message !== 'Storage full') {
                    uploadAlert.innerHTML = `<div class="alert error">❌ Upload failed: ${err.message}</div>`;
                }
            } finally {
                uploadBtn.disabled = false;
                setTimeout(() => {
                    uploadProgress.style.display = 'none';
                }, 2000);
            }
        });

        // Download file
        async function downloadFile(fileId) {
            try {
                // Use proxy endpoint that converts to localhost
                const downloadUrl = `${API_BASE}/download/${fileId}`;
                window.location.href = downloadUrl;
            } catch (err) {
                alert('Download failed: ' + err.message);
            }
        }

        // Delete file
        async function deleteFile(fileId) {
            if (!confirm('Delete this file?')) return;
            
            try {
                const res = await fetch(`${API_BASE}/api/files/${fileId}`, {
                    method: 'DELETE'
                });
                
                if (res.ok) {
                    alert('File deleted successfully!');
                    loadStats();
                    loadFiles();
                } else {
                    alert('Failed to delete file');
                }
            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        // Delete all files
        async function deleteAllFiles() {
            if (!confirm('⚠️ DELETE ALL FILES? This action cannot be undone!')) return;
            if (!confirm('Are you absolutely sure? This will delete ALL files permanently!')) return;
            
            try {
                const res = await fetch(`${API_BASE}/api/files/delete-all`, {
                    method: 'POST'
                });
                
                if (res.ok) {
                    const data = await res.json();
                    alert(`Successfully deleted ${data.deleted_count} file(s)!`);
                    loadStats();
                    loadFiles();
                } else {
                    alert('Failed to delete files');
                }
            } catch (err) {
                alert('Error: ' + err.message);
            }
        }

        // Auto refresh every 5 seconds
        setInterval(() => {
            loadStats();
            loadNodes();
            loadFiles();
        }, 5000);

        // Initial load
        loadStats();
        loadNodes();
        loadFiles();
    </script>
</body>
</html>
"""

if __name__ == '__main__':
    # Start health check thread
    health_thread = threading.Thread(target=health_check_loop, daemon=True)
    health_thread.start()
    
    print("=" * 60)
    print("🚀 Distributed File System - Naming Service (Database)")
    print("=" * 60)
    print("📍 Server running on: http://localhost:5000")
    print("🌐 Web UI: http://localhost:5000")
    print("📊 API Endpoints:")
    print("   - POST /api/nodes/register")
    print("   - POST /api/nodes/heartbeat")
    print("   - POST /api/upload/request")
    print("   - GET  /api/download/<file_id>")
    print("   - GET  /api/files")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
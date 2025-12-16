"""
Distributed File System - Client
Interface untuk upload dan download file
"""

import requests
import os
import hashlib
import argparse
from datetime import datetime
import sys
from pathlib import Path

# Load environment variables dari .env jika ada
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

class DFSClient:
    def __init__(self, host=None, port=None, naming_service_url=None):
        # Priority: explicit URL > host:port > env variables > default
        if naming_service_url:
            self.naming_service_url = naming_service_url
        elif host or port:
            host = host or os.getenv('DFS_HOST', 'localhost')
            port = port or os.getenv('DFS_PORT', '5000')
            self.naming_service_url = f"http://{host}:{port}"
        else:
            host = os.getenv('DFS_HOST', 'localhost')
            port = os.getenv('DFS_PORT', '5000')
            self.naming_service_url = f"http://{host}:{port}"
    
    def calculate_checksum(self, filepath):
        """Hitung SHA-256 checksum file"""
        sha256 = hashlib.sha256()
        with open(filepath, 'rb') as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()
    
    def upload_file(self, filepath, replication_factor=2):
        """Upload file ke DFS"""
        if not os.path.exists(filepath):
            print(f"❌ Error: File tidak ditemukan: {filepath}")
            return None
        
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)
        
        print(f"\n📤 Uploading: {filename} ({file_size} bytes)")
        print(f"🔄 Replication factor: {replication_factor}")
        
        # Step 1: Request upload dari naming service
        try:
            response = requests.post(
                f"{self.naming_service_url}/api/upload/request",
                json={
                    "filename": filename,
                    "file_size": file_size,
                    "replication_factor": replication_factor
                },
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.json().get('error')}")
                return None
            
            data = response.json()
            file_id = data["file_id"]
            upload_nodes = data["upload_nodes"]
            
            print(f"📋 File ID: {file_id}")
            print(f"🎯 Target nodes: {len(upload_nodes)}")
            
        except Exception as e:
            print(f"❌ Error connecting to naming service: {e}")
            return None
        
        # Step 2: Upload ke semua nodes
        with open(filepath, 'rb') as f:
            file_data = f.read()
        
        success_count = 0
        
        for i, node in enumerate(upload_nodes, 1):
            node_id = node["node_id"]
            upload_url = node["upload_url"]
            
            print(f"\n  [{i}/{len(upload_nodes)}] Uploading to {node_id}...")
            
            try:
                files = {'file': (filename, file_data)}
                response = requests.post(upload_url, files=files, timeout=30)
                
                if response.status_code == 200:
                    print(f"  ✅ Success on {node_id}")
                    success_count += 1
                else:
                    print(f"  ❌ Failed on {node_id}: {response.text}")
                    
            except Exception as e:
                print(f"  ❌ Error uploading to {node_id}: {e}")
        
        if success_count == len(upload_nodes):
            print(f"\n✅ Upload complete! File replicated to {success_count} nodes")
            print(f"📋 File ID: {file_id}")
            return file_id
        elif success_count > 0:
            print(f"\n⚠️  Partial success: {success_count}/{len(upload_nodes)} nodes")
            return file_id
        else:
            print(f"\n❌ Upload failed on all nodes")
            return None
    
    def download_file(self, file_id, output_dir="."):
        """Download file dari DFS"""
        print(f"\n📥 Downloading file: {file_id}")
        
        # Step 1: Request download info dari naming service
        try:
            response = requests.get(
                f"{self.naming_service_url}/api/download/{file_id}",
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.json().get('error')}")
                return False
            
            data = response.json()
            filename = data["filename"]
            file_size = data["file_size"]
            checksum = data["checksum"]
            download_urls = data["download_urls"]
            
            print(f"📄 Filename: {filename}")
            print(f"📊 Size: {file_size} bytes")
            print(f"🔐 Checksum: {checksum[:16]}...")
            print(f"🎯 Available nodes: {len(download_urls)}")
            
        except Exception as e:
            print(f"❌ Error connecting to naming service: {e}")
            return False
        
        # Step 2: Download dari node pertama yang available
        output_path = os.path.join(output_dir, filename)
        
        for i, url in enumerate(download_urls, 1):
            print(f"\n  [{i}/{len(download_urls)}] Trying to download from node...")
            
            try:
                response = requests.get(url, timeout=30, stream=True)
                
                if response.status_code == 200:
                    # Save file
                    with open(output_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    # Verify checksum
                    downloaded_checksum = self.calculate_checksum(output_path)
                    
                    if downloaded_checksum == checksum:
                        print(f"  ✅ Download successful!")
                        print(f"  📁 Saved to: {output_path}")
                        print(f"  ✓ Checksum verified")
                        return True
                    else:
                        print(f"  ❌ Checksum mismatch!")
                        os.remove(output_path)
                        
            except Exception as e:
                print(f"  ❌ Error: {e}")
        
        print(f"\n❌ Failed to download from all nodes")
        return False
    
    def list_files(self):
        """List semua file di DFS"""
        try:
            response = requests.get(
                f"{self.naming_service_url}/api/files",
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.json().get('error')}")
                return
            
            data = response.json()
            files = data["files"]
            
            if not files:
                print("\n📂 No files in DFS")
                return
            
            print(f"\n📂 Files in DFS ({len(files)} total):")
            print("=" * 100)
            print(f"{'File ID':<38} {'Filename':<30} {'Size':<12} {'Replicas':<10}")
            print("=" * 100)
            
            for file in files:
                file_id = file["file_id"]
                filename = file["filename"]
                size = file["file_size"]
                replicas = file.get("active_replicas", 0)
                
                size_mb = size / (1024 * 1024)
                if size_mb < 0.01:
                    size_str = f"{size} B"
                else:
                    size_str = f"{size_mb:.2f} MB"
                
                print(f"{file_id:<38} {filename:<30} {size_str:<12} {replicas}")
            
            print("=" * 100)
            
        except Exception as e:
            print(f"❌ Error: {e}")
    
    def delete_file(self, file_id):
        """Delete file dari DFS"""
        print(f"\n🗑️  Deleting file: {file_id}")
        
        try:
            response = requests.delete(
                f"{self.naming_service_url}/api/files/{file_id}",
                timeout=10
            )
            
            if response.status_code == 200:
                print(f"✅ File deleted successfully")
                return True
            else:
                print(f"❌ Error: {response.json().get('error')}")
                return False
                
        except Exception as e:
            print(f"❌ Error: {e}")
            return False
    
    def show_stats(self):
        """Tampilkan statistik DFS"""
        try:
            # Stats dari naming service
            response = requests.get(
                f"{self.naming_service_url}/api/stats",
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Error: {response.json().get('error')}")
                return
            
            stats = response.json()
            
            print(f"\n📊 DFS Statistics:")
            print("=" * 60)
            print(f"Total Nodes:        {stats['total_nodes']}")
            print(f"Active Nodes:       {stats['active_nodes']}")
            print(f"Total Files:        {stats['total_files']}")
            print(f"Total Storage Used: {stats['total_size_mb']} MB")
            print("=" * 60)
            
            # List nodes
            response = requests.get(
                f"{self.naming_service_url}/api/nodes",
                timeout=10
            )
            
            if response.status_code == 200:
                nodes = response.json()["nodes"]
                
                print(f"\n🗄️  Storage Nodes:")
                print("=" * 60)
                
                for node in nodes:
                    node_id = node["node_id"]
                    status = node["status"]
                    files = node["total_files"]
                    space_gb = node["available_space"] / (1024 ** 3)
                    
                    status_icon = "✅" if status == "active" else "❌"
                    print(f"{status_icon} {node_id}")
                    print(f"   Status: {status}")
                    print(f"   Files: {files}")
                    print(f"   Available: {space_gb:.2f} GB")
                    print()
                
                print("=" * 60)
            
        except Exception as e:
            print(f"❌ Error: {e}")

def main():
    parser = argparse.ArgumentParser(description='DFS Client - Distributed File System')
    
    # Network options
    parser.add_argument('--host', type=str, default=None,
                       help='DFS Host (default: localhost or from .env DFS_HOST)')
    parser.add_argument('--port', type=str, default=None,
                       help='DFS Port (default: 5000 or from .env DFS_PORT)')
    parser.add_argument('--naming-service', type=str, default=None,
                       help='Full naming service URL (overrides --host and --port)')
    
    subparsers = parser.add_subparsers(dest='command', help='Command')
    
    # Upload command
    upload_parser = subparsers.add_parser('upload', help='Upload file')
    upload_parser.add_argument('file', type=str, help='File to upload')
    upload_parser.add_argument('--replicas', type=int, default=2,
                              help='Replication factor')
    
    # Download command
    download_parser = subparsers.add_parser('download', help='Download file')
    download_parser.add_argument('file_id', type=str, help='File ID')
    download_parser.add_argument('--output', type=str, default='.',
                                help='Output directory')
    
    # List command
    subparsers.add_parser('list', help='List all files')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete file')
    delete_parser.add_argument('file_id', type=str, help='File ID')
    
    # Stats command
    subparsers.add_parser('stats', help='Show DFS statistics')
    
    args = parser.parse_args()
    
    # Create client with proper parameters
    if args.naming_service:
        client = DFSClient(naming_service_url=args.naming_service)
    else:
        client = DFSClient(host=args.host, port=args.port)
    
    if args.command == 'upload':
        client.upload_file(args.file, args.replicas)
    
    elif args.command == 'download':
        client.download_file(args.file_id, args.output)
    
    elif args.command == 'list':
        client.list_files()
    
    elif args.command == 'delete':
        client.delete_file(args.file_id)
    
    elif args.command == 'stats':
        client.show_stats()
    
    else:
        parser.print_help()

if __name__ == '__main__':
    main()
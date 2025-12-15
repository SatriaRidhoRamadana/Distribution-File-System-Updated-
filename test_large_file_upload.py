"""
PENGUJIAN 9A: Upload File Besar dan Hitung Waktu
Mengupload file dengan ukuran berbeda dan mengukur performa upload
"""

import requests
import time
import os
from datetime import datetime

# Configuration
NAMING_SERVICE_URL = "http://localhost:5000"
TEST_DIR = "test_files"
REPLICATION_FACTOR = 3

# Create test directory jika belum ada
if not os.path.exists(TEST_DIR):
    os.makedirs(TEST_DIR)

def create_large_file(filename, size_mb):
    """Create a large test file dengan ukuran tertentu"""
    filepath = os.path.join(TEST_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(os.urandom(size_mb * 1024 * 1024))
    return filepath

def upload_file(filepath, filename, replication_factor=2):
    """Upload file ke sistem DFS dengan timing"""
    try:
        file_size = os.path.getsize(filepath)
        
        # Step 1: Request upload
        print(f"\n📤 Uploading: {filename}")
        print(f"   Size: {file_size / (1024*1024):.2f} MB")
        
        start_time = time.time()
        
        # Request upload
        req_res = requests.post(
            f"{NAMING_SERVICE_URL}/api/upload/request",
            json={
                "filename": filename,
                "file_size": file_size,
                "replication_factor": replication_factor
            },
            timeout=10
        )
        
        if not req_res.ok:
            print(f"   ❌ Upload request failed: {req_res.json()}")
            return None
        
        req_data = req_res.json()
        file_id = req_data['file_id']
        upload_nodes = req_data['upload_nodes']
        
        print(f"   ✅ Request accepted")
        print(f"   File ID: {file_id}")
        print(f"   Upload nodes: {len(upload_nodes)}")
        
        # Step 2: Upload to nodes
        upload_start = time.time()
        with open(filepath, 'rb') as f:
            file_content = f.read()
        
        upload_promises = []
        for node in upload_nodes:
            upload_url = node['upload_url']
            files = {'file': (filename, file_content)}
            
            node_upload_start = time.time()
            try:
                res = requests.post(upload_url, files=files, timeout=300)
                node_upload_time = time.time() - node_upload_start
                
                if res.ok:
                    print(f"   ✅ Uploaded to {node['node_id']}: {node_upload_time:.2f}s")
                else:
                    print(f"   ❌ Upload to {node['node_id']} failed: {res.status_code}")
            except Exception as e:
                print(f"   ❌ Error uploading to {node['node_id']}: {str(e)}")
        
        upload_time = time.time() - upload_start
        total_time = time.time() - start_time
        
        # Calculate speed
        speed_mbps = (file_size / (1024*1024)) / upload_time if upload_time > 0 else 0
        
        print(f"\n📊 Upload Statistics:")
        print(f"   Upload time: {upload_time:.2f}s")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Speed: {speed_mbps:.2f} MB/s")
        
        return {
            "file_id": file_id,
            "filename": filename,
            "size_mb": file_size / (1024*1024),
            "upload_time": upload_time,
            "total_time": total_time,
            "speed_mbps": speed_mbps,
            "nodes": len(upload_nodes)
        }
        
    except Exception as e:
        print(f"   ❌ Error: {str(e)}")
        return None

def main():
    """Main test function"""
    print("=" * 70)
    print("🧪 PENGUJIAN 9A: Upload File Besar - Hitung Waktu Upload")
    print("=" * 70)
    print(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Target: Upload file berbagai ukuran dan hitung performa")
    print(f"📊 Replication Factor: {REPLICATION_FACTOR}")
    print()
    
    # Test different file sizes
    test_files = [
        ("test_1mb.bin", 1),
        ("test_5mb.bin", 5),
        ("test_10mb.bin", 10),
        ("test_50mb.bin", 50),
    ]
    
    results = []
    total_start = time.time()
    
    for filename, size_mb in test_files:
        print(f"\n{'='*70}")
        print(f"Creating {size_mb}MB test file...")
        filepath = create_large_file(filename, size_mb)
        
        result = upload_file(filepath, filename, REPLICATION_FACTOR)
        if result:
            results.append(result)
        
        # Clean up test file
        os.remove(filepath)
        time.sleep(1)
    
    total_time = time.time() - total_start
    
    # Print summary
    print(f"\n{'='*70}")
    print("📈 SUMMARY - Upload Performance Test")
    print(f"{'='*70}")
    print(f"{'File Size':<12} {'Upload Time':<15} {'Speed':<15} {'Nodes':<8}")
    print(f"{'-'*70}")
    
    for result in results:
        print(f"{result['size_mb']:>6.0f} MB    {result['upload_time']:>8.2f}s      {result['speed_mbps']:>8.2f} MB/s   {result['nodes']:>3}")
    
    if results:
        avg_speed = sum(r['speed_mbps'] for r in results) / len(results)
        total_size = sum(r['size_mb'] for r in results)
        print(f"{'-'*70}")
        print(f"{'Total':<12} {total_time:>8.2f}s      {avg_speed:>8.2f} MB/s (avg)")
        print(f"Total data uploaded: {total_size:.0f} MB")
    
    print(f"\n⏰ End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"✅ Test completed in {total_time:.2f} seconds")
    print("=" * 70)

if __name__ == '__main__':
    main()

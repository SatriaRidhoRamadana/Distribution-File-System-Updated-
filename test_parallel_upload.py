"""
PENGUJIAN 9B: Upload File Banyak Sekaligus (Parallel Upload)
Upload multiple files secara bersamaan dan hitung waktu total
"""

import requests
import time
import os
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Configuration
NAMING_SERVICE_URL = "http://localhost:5000"
TEST_DIR = "test_files_batch"
REPLICATION_FACTOR = 3
MAX_WORKERS = 5  # Jumlah upload concurrent

# Create test directory jika belum ada
if not os.path.exists(TEST_DIR):
    os.makedirs(TEST_DIR)

# Thread-safe lock untuk print
print_lock = threading.Lock()

def safe_print(*args, **kwargs):
    """Thread-safe print"""
    with print_lock:
        print(*args, **kwargs)

def create_test_file(filename, size_mb):
    """Create a test file dengan ukuran tertentu"""
    filepath = os.path.join(TEST_DIR, filename)
    with open(filepath, 'wb') as f:
        f.write(os.urandom(size_mb * 1024 * 1024))
    return filepath

def upload_single_file(file_info, file_index):
    """Upload single file ke DFS"""
    filename, size_mb = file_info
    filepath = os.path.join(TEST_DIR, filename)
    
    try:
        file_size = os.path.getsize(filepath)
        
        safe_print(f"\n[File {file_index}] 📤 Uploading: {filename} ({size_mb}MB)")
        
        start_time = time.time()
        
        # Request upload
        req_res = requests.post(
            f"{NAMING_SERVICE_URL}/api/upload/request",
            json={
                "filename": filename,
                "file_size": file_size,
                "replication_factor": REPLICATION_FACTOR
            },
            timeout=10
        )
        
        if not req_res.ok:
            safe_print(f"[File {file_index}] ❌ Upload request failed: {req_res.json()}")
            return None
        
        req_data = req_res.json()
        file_id = req_data['file_id']
        upload_nodes = req_data['upload_nodes']
        
        safe_print(f"[File {file_index}] ✅ Request accepted - {len(upload_nodes)} nodes")
        
        # Upload to nodes
        upload_start = time.time()
        with open(filepath, 'rb') as f:
            file_content = f.read()
        
        for node in upload_nodes:
            upload_url = node['upload_url']
            files = {'file': (filename, file_content)}
            
            try:
                res = requests.post(upload_url, files=files, timeout=300)
                if not res.ok:
                    safe_print(f"[File {file_index}] ⚠️  Upload to {node['node_id']} failed: {res.status_code}")
            except Exception as e:
                safe_print(f"[File {file_index}] ⚠️  Error uploading to {node['node_id']}: {str(e)}")
        
        upload_time = time.time() - upload_start
        total_time = time.time() - start_time
        speed_mbps = (file_size / (1024*1024)) / upload_time if upload_time > 0 else 0
        
        safe_print(f"[File {file_index}] ✅ Complete: {upload_time:.2f}s ({speed_mbps:.2f} MB/s)")
        
        return {
            "file_id": file_id,
            "filename": filename,
            "size_mb": size_mb,
            "upload_time": upload_time,
            "total_time": total_time,
            "speed_mbps": speed_mbps
        }
        
    except Exception as e:
        safe_print(f"[File {file_index}] ❌ Error: {str(e)}")
        return None

def main():
    """Main test function"""
    print("=" * 70)
    print("🧪 PENGUJIAN 9B: Upload File Banyak Sekaligus (Parallel)")
    print("=" * 70)
    print(f"⏰ Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Target: Upload 10 files secara parallel dan hitung waktu total")
    print(f"📊 Replication Factor: {REPLICATION_FACTOR}")
    print(f"🔀 Concurrent uploads: {MAX_WORKERS}")
    print()
    
    # Define test files - 10 files
    test_files = [
        ("file1_2mb.bin", 2),
        ("file2_3mb.bin", 3),
        ("file3_2mb.bin", 2),
        ("file4_4mb.bin", 4),
        ("file5_3mb.bin", 3),
        ("file6_2mb.bin", 2),
        ("file7_3mb.bin", 3),
        ("file8_2mb.bin", 2),
        ("file9_4mb.bin", 4),
        ("file10_3mb.bin", 3),
    ]
    
    # Create all test files
    print("📝 Creating test files...")
    for filename, size_mb in test_files:
        create_test_file(filename, size_mb)
        print(f"   ✓ {filename} ({size_mb}MB)")
    
    print(f"\n📤 Starting parallel uploads ({MAX_WORKERS} concurrent)...\n")
    
    results = []
    total_start = time.time()
    
    # Upload files in parallel
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(upload_single_file, file_info, i+1): i+1 
            for i, file_info in enumerate(test_files)
        }
        
        for future in as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
    
    total_time = time.time() - total_start
    
    # Clean up test files
    print("\n🧹 Cleaning up test files...")
    for filename, _ in test_files:
        filepath = os.path.join(TEST_DIR, filename)
        if os.path.exists(filepath):
            os.remove(filepath)
    
    # Print summary
    print(f"\n{'='*70}")
    print("📈 SUMMARY - Parallel Upload Test")
    print(f"{'='*70}")
    print(f"{'Filename':<20} {'Size':<8} {'Upload Time':<15} {'Speed':<15}")
    print(f"{'-'*70}")
    
    total_size = 0
    total_upload_time = 0
    for result in sorted(results, key=lambda x: x['filename']):
        total_size += result['size_mb']
        total_upload_time += result['upload_time']
        print(f"{result['filename']:<20} {result['size_mb']:>5.0f}MB  {result['upload_time']:>10.2f}s     {result['speed_mbps']:>10.2f} MB/s")
    
    print(f"{'-'*70}")
    avg_speed = total_size / total_upload_time if total_upload_time > 0 else 0
    
    print(f"Total data: {total_size:.0f}MB")
    print(f"Sequential upload time: {total_upload_time:.2f}s")
    print(f"Parallel upload time: {total_time:.2f}s")
    print(f"Speed improvement: {(total_upload_time / total_time):.1f}x faster")
    print(f"Average speed: {avg_speed:.2f} MB/s")
    print(f"Throughput: {total_size / total_time:.2f} MB/s")
    
    print(f"\n⏰ End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"✅ Test completed in {total_time:.2f} seconds")
    print("=" * 70)

if __name__ == '__main__':
    main()

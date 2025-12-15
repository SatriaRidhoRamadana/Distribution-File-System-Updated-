"""
Test Script - Storage Full Scenario
Test upload file ketika storage node penuh (limit 10 MB per node)
"""

import requests
import io
import time

NAMING_SERVICE_URL = "http://localhost:5000"

def create_dummy_file(size_mb):
    """Create dummy file dengan ukuran tertentu"""
    size_bytes = int(size_mb * 1024 * 1024)
    content = b'X' * size_bytes
    return io.BytesIO(content)

def upload_file(filename, file_size_mb, replication_factor=3):
    """Upload file ke DFS"""
    print(f"\n{'='*70}")
    print(f"Uploading: {filename} ({file_size_mb} MB) with replication={replication_factor}")
    print(f"{'='*70}")
    
    # Create file
    file_data = create_dummy_file(file_size_mb)
    
    # Step 1: Request upload
    print(f"[1/3] Requesting upload slots...")
    response = requests.post(
        f"{NAMING_SERVICE_URL}/api/upload/request",
        json={
            "filename": filename,
            "file_size": int(file_size_mb * 1024 * 1024),
            "replication_factor": replication_factor
        }
    )
    
    if response.status_code != 200:
        error_data = response.json()
        print(f"\n❌ UPLOAD FAILED - Status: {response.status_code}")
        print(f"   Error: {error_data.get('error')}")
        print(f"   Message: {error_data.get('message')}")
        
        if error_data.get('status') == 'storage_full':
            print(f"\n   💾 Storage Full Details:")
            print(f"   - Required nodes: {error_data.get('required_nodes')}")
            print(f"   - Available nodes with space: {error_data.get('available_nodes_with_space')}")
            print(f"\n   Node Information:")
            for node_info in error_data.get('nodes_info', []):
                print(f"   • {node_info['node_id']}: {node_info['available_space_mb']:.2f} MB available (need {node_info['required_space_mb']:.2f} MB)")
        
        return False
    
    req_data = response.json()
    file_id = req_data['file_id']
    upload_nodes = req_data['upload_nodes']
    
    print(f"   ✅ Upload slots allocated: {len(upload_nodes)} nodes")
    for node in upload_nodes:
        print(f"      - {node['node_id']}")
    
    # Step 2: Upload to nodes
    print(f"\n[2/3] Uploading to storage nodes...")
    successful_uploads = 0
    failed_uploads = 0
    
    for node in upload_nodes:
        file_data.seek(0)  # Reset file pointer
        files = {'file': (filename, file_data, 'application/octet-stream')}
        
        try:
            upload_response = requests.post(node['upload_url'], files=files, timeout=30)
            
            if upload_response.status_code == 200:
                print(f"   ✅ {node['node_id']}: Success")
                successful_uploads += 1
            else:
                error_data = upload_response.json()
                print(f"   ❌ {node['node_id']}: Failed - {error_data.get('error')}")
                if 'available_mb' in error_data:
                    print(f"      Available: {error_data['available_mb']:.2f} MB, Used: {error_data['used_mb']:.2f} MB")
                failed_uploads += 1
                
        except Exception as e:
            print(f"   ❌ {node['node_id']}: Error - {str(e)}")
            failed_uploads += 1
    
    print(f"\n[3/3] Upload Summary:")
    print(f"   ✅ Successful: {successful_uploads}/{len(upload_nodes)}")
    print(f"   ❌ Failed: {failed_uploads}/{len(upload_nodes)}")
    
    return successful_uploads > 0

def check_node_status():
    """Check status semua nodes"""
    print(f"\n{'='*70}")
    print(f"Storage Nodes Status")
    print(f"{'='*70}")
    
    response = requests.get(f"{NAMING_SERVICE_URL}/api/nodes")
    if response.status_code == 200:
        data = response.json()
        
        for node in data['nodes']:
            status_icon = "🟢" if node['status'] == 'active' else "🔴"
            print(f"\n{status_icon} {node['node_id']}")
            print(f"   Status: {node['status']}")
            print(f"   Address: {node['node_address']}")
            print(f"   Files: {node['total_files']}")
            print(f"   Available Space: {node['available_space'] / (1024**2):.2f} MB")
            
            # Get detailed health info
            try:
                health_response = requests.get(f"{node['node_address']}/health")
                if health_response.status_code == 200:
                    health_data = health_response.json()
                    used_mb = health_data.get('used_space', 0) / (1024**2)
                    max_mb = health_data.get('max_storage', 0)
                    if max_mb:
                        max_mb = max_mb / (1024**2)
                        percentage = health_data.get('storage_percentage', 0)
                        print(f"   Used Space: {used_mb:.2f} MB / {max_mb:.2f} MB ({percentage:.1f}%)")
            except:
                pass

def main():
    """Main test function"""
    print(f"\n{'#'*70}")
    print(f"# TEST: Storage Full Scenario")
    print(f"# Storage Limit: 10 MB per node")
    print(f"# Replication Factor: 3 (all nodes)")
    print(f"{'#'*70}")
    
    # Check initial status
    check_node_status()
    
    # Test 1: Upload file 2 MB (should success)
    print(f"\n\n{'#'*70}")
    print(f"# Test 1: Upload 2 MB file (should SUCCESS)")
    print(f"{'#'*70}")
    upload_file("test_2mb.dat", 2, replication_factor=3)
    time.sleep(1)
    check_node_status()
    
    # Test 2: Upload file 3 MB (should success)
    print(f"\n\n{'#'*70}")
    print(f"# Test 2: Upload 3 MB file (should SUCCESS)")
    print(f"{'#'*70}")
    upload_file("test_3mb.dat", 3, replication_factor=3)
    time.sleep(1)
    check_node_status()
    
    # Test 3: Upload file 2 MB (should success)
    print(f"\n\n{'#'*70}")
    print(f"# Test 3: Upload 2 MB file (should SUCCESS)")
    print(f"{'#'*70}")
    upload_file("test_2mb_2.dat", 2, replication_factor=3)
    time.sleep(1)
    check_node_status()
    
    # Test 4: Upload file 3 MB (should FAIL - storage full)
    print(f"\n\n{'#'*70}")
    print(f"# Test 4: Upload 3 MB file (should FAIL - storage full)")
    print(f"{'#'*70}")
    upload_file("test_3mb_fail.dat", 3, replication_factor=3)
    time.sleep(1)
    check_node_status()
    
    # Test 5: Upload file 1 MB (might success if space < 2MB available)
    print(f"\n\n{'#'*70}")
    print(f"# Test 5: Upload 1 MB file (check remaining space)")
    print(f"{'#'*70}")
    upload_file("test_1mb.dat", 1, replication_factor=3)
    time.sleep(1)
    check_node_status()
    
    print(f"\n\n{'#'*70}")
    print(f"# Test Completed!")
    print(f"{'#'*70}\n")

if __name__ == "__main__":
    main()

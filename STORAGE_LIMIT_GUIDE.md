# Storage Capacity Management - Test Guide

## Konfigurasi Storage Limit

### 1. Naming Service (`naming_service.py`)
```python
MAX_STORAGE_PER_NODE = 10 * 1024 * 1024  # 10 MB for testing
MIN_SPACE_BUFFER = 1 * 1024 * 1024       # 1 MB buffer
```

### 2. Storage Node (`storage_node.py`)
```python
MAX_STORAGE_SIZE = 10 * 1024 * 1024  # 10 MB limit for testing
# Set to None for unlimited storage
```

## Fitur Validasi Storage

### Backend (Naming Service)
- ✅ Validasi kapasitas sebelum upload
- ✅ Filter nodes dengan space cukup
- ✅ Return error 507 jika storage penuh
- ✅ Detail informasi available space per node

### Storage Node
- ✅ Validasi space saat menerima file
- ✅ Hitung used space vs max storage
- ✅ Return error 507 jika tidak cukup space
- ✅ Health endpoint menampilkan storage usage

### Frontend (Web UI)
- ✅ Notifikasi storage penuh dengan detail
- ✅ Tampilkan available space per node
- ✅ Alert jelas dengan breakdown nodes

## Cara Testing

### 1. Restart Semua Services
```powershell
# Stop all Python processes
Get-Process | Where-Object {$_.ProcessName -eq "python"} | Stop-Process -Force

# Start naming service
python naming_service.py

# Start storage nodes (terminal terpisah)
python storage_node.py --port 5001 --storage-dir ./storage/node1
python storage_node.py --port 5002 --storage-dir ./storage/node2
python storage_node.py --port 5003 --storage-dir ./storage/node3
```

### 2. Clean Storage (Optional)
```powershell
Remove-Item -Recurse -Force ./storage/node1/*
Remove-Item -Recurse -Force ./storage/node2/*
Remove-Item -Recurse -Force ./storage/node3/*
Remove-Item -Force dfs.db
```

### 3. Run Test Script
```powershell
python test_storage_full.py
```

## Test Scenario

Script akan upload file dengan urutan:
1. **2 MB** - Should SUCCESS (total 2/10 MB)
2. **3 MB** - Should SUCCESS (total 5/10 MB)
3. **2 MB** - Should SUCCESS (total 7/10 MB)
4. **3 MB** - Should FAIL (need 3+1=4 MB, available ~3 MB)
5. **1 MB** - Check if can fit in remaining space

## Expected Behavior

### Success Upload
```
✅ File uploaded successfully!
- All 3 nodes received the file
- Database updated with active replicas
```

### Storage Full Error
```
❌ Upload Failed: Storage nodes tidak memiliki cukup space

Detail Nodes:
• node1: 2.85 MB available (need 4.00 MB)
• node2: 2.85 MB available (need 4.00 MB)
• node3: 2.85 MB available (need 4.00 MB)
```

## Monitoring

### Check Node Status
```powershell
curl http://localhost:5001/health
curl http://localhost:5002/health
curl http://localhost:5003/health
```

Response:
```json
{
  "status": "healthy",
  "node_id": "node1",
  "available_space": 2990000,
  "used_space": 7010000,
  "max_storage": 10000000,
  "file_count": 3,
  "storage_percentage": 70.1
}
```

## Disable Storage Limit (Production)

Untuk production dengan unlimited storage:

### storage_node.py
```python
MAX_STORAGE_SIZE = None  # Unlimited
```

Sistem akan fallback ke disk space monitoring.

## Notes

- Buffer 1 MB ditambahkan untuk safety margin
- Upload request di-reject SEBELUM file dikirim (efisien)
- Partial upload ke beberapa node akan di-detect dan failed
- Web UI menampilkan detail error dengan breakdown per node

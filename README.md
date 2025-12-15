## SISTEM TERDISTRIBUSI - Distributed File System (DFS)
    1. Satria Ridho Ramadana - 2301020077
    2. Kaka Puri             - 2301020078
    3. Nisa Nur Rahmadani    - 2301020081
    4. Hana Syakira Aini     - 2301020083

DFS ini terdiri dari Naming Service sebagai koordinator metadata + routing, tiga Storage Node untuk replikasi data, serta web UI/CLI untuk operasi upload, download, delete, monitoring, dan auto-recovery ketika node kembali online.


## Folder Structure (copy-friendly)

```
Sist\
├─ naming_service.py           (coordinator + web UI)
├─ storage_node.py             (storage server)
├─ dfs_client.py               (CLI client)
├─ database_schema.py          (SQLite metadata)
├─ test_large_file_upload.py
├─ test_parallel_upload.py
├─ test_storage_full.py        (simulate node storage limit)
├─ STORAGE_LIMIT_GUIDE.md      (how to configure storage limits)
├─ metadata.json | nodes.json
├─ requirements.txt
├─ start_system.bat
├─ storage\
│  ├─ node1\  (primary files)
│  ├─ node2\  (replica files)
│  └─ node3\  (replica files)
└─ README.md
### Deskripsi Folder/File
- `naming_service.py` : Naming Service (koordinator), REST API, web UI dashboard, metadata & routing, health check, upload/download orchestration, recovery.
- `storage_node.py`   : Storage node server (upload/download/delete/verify), heartbeat ke naming service, limit storage opsional.
- `dfs_client.py`     : CLI client untuk upload/download/list via HTTP API.
- `database_schema.py`: Schema & akses SQLite untuk files, replicas, storage_nodes.
- `test_large_file_upload.py` : Uji performa upload file besar (1–50 MB) dengan replication 3.
- `test_parallel_upload.py`   : Uji throughput paralel vs sequential (10 file, 5 workers).
- `STORAGE_LIMIT_GUIDE.md`    : Panduan konfigurasi limit storage per node dan cara test penuh.
- `metadata.json | nodes.json`: Konfigurasi/metadata tambahan untuk sistem.
- `requirements.txt`          : Dependensi Python.
- `start_system.bat`          : Skrip cepat untuk menjalankan sistem.
- `storage/`                  : Direktori penyimpanan fisik; berisi `node1/`, `node2/`, `node3/`.
```

---

## Available Test Scripts

### 1. Start Services (Buka 3 Terminal)
```powershell
# Terminal 1
cd C:\Users\ASUS\Downloads\Sist\Sist
.\venv\Scripts\Activate.ps1
python naming_service.py

# Terminal 2
.\venv\Scripts\Activate.ps1
python storage_node.py --port 5001 --storage-dir ./storage/node1

# Terminal 3
.\venv\Scripts\Activate.ps1
python storage_node.py --port 5002 --storage-dir ./storage/node2

# Terminal 4
.\venv\Scripts\Activate.ps1
python storage_node.py --port 5003 --storage-dir ./storage/node3
```
## API Endpoints

### Naming Service (port 5000)
- GET `/`                   : Web UI dashboard
- GET `/health`            : Health check naming service
- POST `/api/nodes/register` : Register storage node
- POST `/api/nodes/heartbeat`: Heartbeat from node (available space, file count)
- GET `/api/nodes`         : List all nodes + status
- POST `/api/upload/request`: Request upload (allocates file_id + upload URLs)
- POST `/api/upload/confirm`: Confirm successful upload per node
- POST `/api/upload/cancel` : Cancel upload and cleanup DB records
- GET `/api/download/<file_id>`: Get direct download URLs from active replicas
- GET `/download/<file_id>`: Proxy download via naming service
- GET `/api/files`         : List all files + replica status
- GET `/api/files/<file_id>`: Detail file
- DELETE `/api/files/<file_id>`: Delete file from all replicas
- POST `/api/files/delete-all` : Delete all files
- GET `/api/stats`         : System statistics (files, nodes, size)
- GET `/api/history`       : Upload history

### Storage Node (ports 5001-5003)
- GET `/health`            : Node health (available, used, max storage)
- POST `/upload/<file_id>` : Upload file to node
- GET `/download/<file_id>`: Download file from node
- DELETE `/delete/<file_id>`: Delete file on node
- GET `/verify/<file_id>`  : Verify file existence + checksum
- GET `/stats`             : Node stats


### 2. Upload & Test
```powershell
# Terminal 4 (baru)
echo "Test file" > test.txt
python dfs_client.py upload test.txt --replicas 2
# CATAT FILE_ID yang muncul!
```

### 3. Test Recovery
```powershell
# Kill Terminal 2 (Ctrl+C)
# Tunggu 35 detik
# Download masih work! (dari node2)
python dfs_client.py download [FILE_ID]

# Restart Terminal 2
python storage_node.py --port 5001 --storage-dir ./storage/node1
# Recovery otomatis!
```

---

## 📋 COMMAND REFERENCE

### Check Node Status
```powershell
python -c "import requests; [print(f'{n[\"node_id\"]}: {n[\"status\"]}') for n in requests.get('http://localhost:5000/api/nodes').json()['nodes']]"
```

### List All Files
```powershell
python dfs_client.py list
```

### Upload File
```powershell
python dfs_client.py upload <filename> --replication 2
```

### Download File
```powershell
python dfs_client.py download <file_id>
```

### Kill Node (Manual)
```powershell
# Find PID
netstat -ano | findstr :5001

# Kill
taskkill /PID [PID] /F
```

### Kill All Python
```powershell
taskkill /F /IM python.exe
```

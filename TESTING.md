# Pengujian Fungsional - Distributed File System

## Fitur yang Diuji
- Upload file
- Download file
- Upload file berukuran besar
- Upload paralel
- Penanganan storage penuh

## Cara Menjalankan
```powershell
python naming_service.py
python storage_node.py --port 5001
python storage_node.py --port 5002
python storage_node.py --port 5003

python test_large_file_upload.py
python test_parallel_upload.py
python test_storage_full.py
```
## Pengujian

✅ Sistem berjalan normal
✅ Upload dan download file berhasil
⚠️ Upload paralel diuji dengan file terbatas
✅ Upload ditolak saat storage penuh
@echo off
echo Starting Distributed File System...

start "Naming Service" python naming_service.py
timeout /t 2 /nobreak > nul

start "Storage Node 1" python storage_node.py --port 5001 --storage-dir ./storage/node1
start "Storage Node 2" python storage_node.py --port 5002 --storage-dir ./storage/node2
start "Storage Node 3" python storage_node.py --port 5003 --storage-dir ./storage/node3
start "demo_script" python demo_script.py 

echo.
echo All services started!
echo Press any key to exit...
pause > nul
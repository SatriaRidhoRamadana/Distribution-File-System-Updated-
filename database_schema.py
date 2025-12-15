"""
Distributed File System - Database Models
SQLite database untuk metadata persistence
"""

import sqlite3
import json
from datetime import datetime
from contextlib import contextmanager

class DFSDatabase:
    def __init__(self, db_path="dfs.db"):
        self.db_path = db_path
        self.init_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager untuk database connection"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def init_database(self):
        """Initialize database schema"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Table: files
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    file_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    checksum TEXT,
                    upload_timestamp TEXT NOT NULL,
                    replication_factor INTEGER DEFAULT 2,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table: replicas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS replicas (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    node_id TEXT NOT NULL,
                    node_address TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    last_verified TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
                )
            """)
            
            # Table: storage_nodes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS storage_nodes (
                    node_id TEXT PRIMARY KEY,
                    node_address TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    available_space INTEGER DEFAULT 0,
                    total_files INTEGER DEFAULT 0,
                    last_heartbeat TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Table: upload_history
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS upload_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    upload_timestamp TEXT NOT NULL,
                    success INTEGER DEFAULT 1,
                    FOREIGN KEY (file_id) REFERENCES files(file_id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_replicas_file ON replicas(file_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_replicas_node ON replicas(node_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_nodes_status ON storage_nodes(status)")
            
            conn.commit()
    
    # === FILE OPERATIONS ===
    
    def create_file(self, file_id, filename, file_size, replication_factor=2):
        """Create new file record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO files (file_id, filename, file_size, upload_timestamp, replication_factor)
                VALUES (?, ?, ?, ?, ?)
            """, (file_id, filename, file_size, datetime.now().isoformat(), replication_factor))
            
            # Add to upload history
            cursor.execute("""
                INSERT INTO upload_history (file_id, filename, file_size, upload_timestamp)
                VALUES (?, ?, ?, ?)
            """, (file_id, filename, file_size, datetime.now().isoformat()))
            
            return file_id
    
    def get_file(self, file_id):
        """Get file information"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            
            if row:
                file_data = dict(row)
                
                # Get replicas
                cursor.execute("""
                    SELECT * FROM replicas WHERE file_id = ?
                """, (file_id,))
                
                file_data['replicas'] = [dict(r) for r in cursor.fetchall()]
                return file_data
            
            return None
    
    def list_files(self, limit=100, offset=0):
        """List all files with pagination"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Get total count
            cursor.execute("SELECT COUNT(*) as count FROM files")
            total = cursor.fetchone()['count']
            
            # Get files
            cursor.execute("""
                SELECT f.*, 
                       COUNT(r.id) as replica_count,
                       SUM(CASE WHEN r.status = 'active' THEN 1 ELSE 0 END) as active_replicas
                FROM files f
                LEFT JOIN replicas r ON f.file_id = r.file_id
                GROUP BY f.file_id
                ORDER BY f.upload_timestamp DESC
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            files = [dict(row) for row in cursor.fetchall()]
            
            return {
                'files': files,
                'total': total,
                'limit': limit,
                'offset': offset
            }
    
    def update_file_checksum(self, file_id, checksum):
        """Update file checksum"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE files SET checksum = ? WHERE file_id = ?
            """, (checksum, file_id))
    
    def delete_file(self, file_id):
        """Delete file and its replicas"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
            cursor.execute("DELETE FROM replicas WHERE file_id = ?", (file_id,))
            return cursor.rowcount > 0
    
    # === REPLICA OPERATIONS ===
    
    def add_replica(self, file_id, node_id, node_address, status='pending'):
        """Add replica record"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO replicas (file_id, node_id, node_address, status)
                VALUES (?, ?, ?, ?)
            """, (file_id, node_id, node_address, status))
            return cursor.lastrowid
    
    def update_replica_status(self, file_id, node_id, status='active'):
        """Update replica status"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE replicas 
                SET status = ?, last_verified = ?
                WHERE file_id = ? AND node_id = ?
            """, (status, datetime.now().isoformat(), file_id, node_id))
    
    def get_replicas(self, file_id):
        """Get all replicas for a file"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM replicas WHERE file_id = ?", (file_id,))
            return [dict(row) for row in cursor.fetchall()]
    
    # === NODE OPERATIONS ===
    
    def register_node(self, node_id, node_address):
        """Register or update storage node"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO storage_nodes (node_id, node_address, last_heartbeat)
                VALUES (?, ?, ?)
                ON CONFLICT(node_id) DO UPDATE SET
                    node_address = excluded.node_address,
                    status = 'active',
                    last_heartbeat = excluded.last_heartbeat
            """, (node_id, node_address, datetime.now().isoformat()))
    
    def update_node_heartbeat(self, node_id, available_space, total_files):
        """Update node heartbeat"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE storage_nodes 
                SET last_heartbeat = ?,
                    available_space = ?,
                    total_files = ?,
                    status = 'active'
                WHERE node_id = ?
            """, (datetime.now().isoformat(), available_space, total_files, node_id))
            return cursor.rowcount > 0
    
    def get_active_nodes(self, timeout_seconds=30):
        """Get all active nodes"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cutoff_time = datetime.now().timestamp() - timeout_seconds
            
            cursor.execute("""
                SELECT * FROM storage_nodes
                WHERE status = 'active'
                ORDER BY available_space DESC
            """)
            
            nodes = []
            current_time = datetime.now()
            
            for row in cursor.fetchall():
                node = dict(row)
                last_hb = datetime.fromisoformat(node['last_heartbeat'])
                
                # Check if node is still active
                if (current_time - last_hb).total_seconds() < timeout_seconds:
                    nodes.append(node)
                else:
                    # Mark as inactive
                    self.mark_node_inactive(node['node_id'])
            
            return nodes
    
    def mark_node_inactive(self, node_id):
        """Mark node as inactive"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE storage_nodes SET status = 'inactive' WHERE node_id = ?
            """, (node_id,))
    
    def get_all_nodes(self):
        """Get all nodes"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM storage_nodes ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]
    
    # === STATISTICS ===
    
    def get_stats(self):
        """Get system statistics"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Total files
            cursor.execute("SELECT COUNT(*) as count, COALESCE(SUM(file_size), 0) as total_size FROM files")
            file_stats = dict(cursor.fetchone())
            
            # Active nodes
            cursor.execute("SELECT COUNT(*) as count FROM storage_nodes WHERE status = 'active'")
            active_nodes = cursor.fetchone()['count']
            
            # Total nodes
            cursor.execute("SELECT COUNT(*) as count FROM storage_nodes")
            total_nodes = cursor.fetchone()['count']
            
            # Recent uploads (last 24 hours)
            cursor.execute("""
                SELECT COUNT(*) as count 
                FROM upload_history 
                WHERE upload_timestamp > datetime('now', '-1 day')
            """)
            recent_uploads = cursor.fetchone()['count']
            
            return {
                'total_files': file_stats['count'],
                'total_size': file_stats['total_size'],
                'total_nodes': total_nodes,
                'active_nodes': active_nodes,
                'recent_uploads': recent_uploads
            }
    
    def get_upload_history(self, limit=50):
        """Get upload history"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM upload_history
                ORDER BY upload_timestamp DESC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]
#!/usr/bin/env python3

import os
import sys
import stat
import errno
import time
import yaml
from fuse import FUSE, FuseOSError, Operations
from dotenv import load_dotenv

from issue_api.jira_api import Jira

# --- SECRETS ---
load_dotenv()

jira_api_key = os.getenv('JIRA_API_TOKEN')
if not jira_api_key:
    raise ValueError('You must set JIRA_API_TOKEN environment variable in .env file before running this script!')

jira_url = os.getenv('JIRA_URL')
if not jira_url:
    raise ValueError('You must set JIRA_URL environment variable in .env file before running this script!')

# Initialize JIRA client at module level
jira_client = Jira(jira_url, jira_api_key)


class QueryFolder:
    """Represents a query folder with its configuration and cached issues."""
    
    def __init__(self, name):
        self.name = name
        self.enabled = False
        self.jira_config = {'jql': ''}
        self.issues = []
        self.last_updated = 0
        
    def to_yaml(self):
        """Convert configuration to YAML string."""
        return yaml.dump({
            'enabled': self.enabled,
            'jira': [self.jira_config]
        }, default_flow_style=False)
    
    def from_yaml(self, yaml_content):
        """Load configuration from YAML string."""
        try:
            data = yaml.safe_load(yaml_content)
            if data:
                self.enabled = data.get('enabled', False)
                jira_list = data.get('jira', [])
                if jira_list and isinstance(jira_list, list) and len(jira_list) > 0:
                    self.jira_config = jira_list[0]
                else:
                    self.jira_config = {'jql': ''}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML: {e}")
    
    def update_issues(self, jira_client):
        """Fetch issues from JIRA if enabled."""
        jql = self.jira_config.get('jql', '')
        if self.enabled and jql:
            try:
                self.issues = jira_client.search(jql)
                self.last_updated = time.time()
                print(f"Updated {self.name}: found {len(self.issues)} issues")
            except Exception as e:
                print(f"Error fetching issues for {self.name}: {e}")
                self.issues = []
        else:
            self.issues = []


class JiraFS(Operations):
    """
    FUSE filesystem that mounts JIRA issues as files.
    
    Structure:
    /
    ├── query_folder_1/
    │   ├── config.yaml
    │   ├── ISSUE-123.txt
    │   └── ISSUE-456.txt
    └── query_folder_2/
        ├── config.yaml
        └── ...
    """
    
    def __init__(self, jira_client):
        self.jira = jira_client
        self.folders = {}  # folder_name -> QueryFolder
        self.file_handles = {}  # path -> content
        self.now = time.time()
        
        # Fetch JIRA version info at startup
        print("Testing JIRA connection...")
        self.version_info = jira_client.version()
        if self.version_info.get('success'):
            print(f"✓ Connected to {self.version_info.get('server_title', 'JIRA')}")
            print(f"✓ Version: {self.version_info['version']}")
            print(f"✓ Base URL: {self.version_info['base_url']}")
        else:
            print(f"✗ Warning: Could not connect to JIRA: {self.version_info.get('error', 'Unknown error')}")
            print("  Filesystem will still mount, but queries may fail.")
        print()
        
    def _get_folder_from_path(self, path):
        """Extract folder name from path."""
        parts = path.strip('/').split('/')
        if len(parts) > 0 and parts[0]:
            return parts[0]
        return None
    
    def _get_filename_from_path(self, path):
        """Extract filename from path."""
        parts = path.strip('/').split('/')
        if len(parts) >= 2:
            return parts[1]
        return None
    
    def _is_config_file(self, path):
        """Check if path is a config.yaml file."""
        filename = self._get_filename_from_path(path)
        return filename == 'config.yaml'
    
    def _get_issue_file_content(self, folder_name, filename):
        """Get the content of an issue file."""
        if folder_name not in self.folders:
            return None
        
        folder = self.folders[folder_name]
        # Remove .txt extension to get issue key
        issue_key = filename[:-4] if filename.endswith('.txt') else filename
        
        for issue in folder.issues:
            if issue.key == issue_key:
                return issue.to_ai().encode('utf-8')
        
        return None
    
    def _get_root_version_content(self):
        """Generate content for version.txt file at root."""
        if not self.version_info:
            return "No version information available"
        
        version_info = self.version_info
        if version_info.get('success'):
            lines = []
            lines.append(f"JIRA Server Information")
            lines.append(f"=" * 40)
            lines.append(f"Server: {version_info.get('server_title', 'JIRA')}")
            lines.append(f"Version: {version_info.get('version', 'unknown')}")
            lines.append(f"Build: {version_info.get('build', 'unknown')}")
            lines.append(f"Base URL: {version_info.get('base_url', 'unknown')}")
            lines.append(f"")
            lines.append(f"Connection tested at mount time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.now))}")
            return "\n".join(lines)
        else:
            return f"Error getting version: {version_info.get('error', 'Unknown error')}"
    
    def getattr(self, path, fh=None):
        """Get file attributes."""
        now = int(self.now)
        
        # Root directory
        if path == '/':
            return {
                'st_mode': (stat.S_IFDIR | 0o755),
                'st_nlink': 2,
                'st_size': 0,
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now
            }
        
        # version.txt in root directory
        if path == '/version.txt':
            content = self._get_root_version_content().encode('utf-8')
            return {
                'st_mode': (stat.S_IFREG | 0o444),  # Read-only
                'st_nlink': 1,
                'st_size': len(content),
                'st_ctime': now,
                'st_mtime': now,
                'st_atime': now
            }
        
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        # Query folder directory
        if folder_name and not filename:
            if folder_name in self.folders:
                return {
                    'st_mode': (stat.S_IFDIR | 0o755),
                    'st_nlink': 2,
                    'st_size': 0,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_atime': now
                }
        
        # Files inside query folder
        if folder_name and filename:
            if folder_name not in self.folders:
                raise FuseOSError(errno.ENOENT)
            
            folder = self.folders[folder_name]
            
            # config.yaml file
            if filename == 'config.yaml':
                content = folder.to_yaml().encode('utf-8')
                return {
                    'st_mode': (stat.S_IFREG | 0o644),
                    'st_nlink': 1,
                    'st_size': len(content),
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_atime': now
                }
            
            # Issue file
            if filename.endswith('.txt'):
                content = self._get_issue_file_content(folder_name, filename)
                if content is not None:
                    return {
                        'st_mode': (stat.S_IFREG | 0o444),  # Read-only
                        'st_nlink': 1,
                        'st_size': len(content),
                        'st_ctime': now,
                        'st_mtime': now,
                        'st_atime': now
                    }
        
        raise FuseOSError(errno.ENOENT)
    
    def readdir(self, path, fh):
        """Read directory contents."""
        yield '.'
        yield '..'
        
        # Root directory - list all query folders and version.txt
        if path == '/':
            yield 'version.txt'  # Always show version.txt at root
            for folder_name in self.folders.keys():
                yield folder_name
        else:
            # Inside a query folder - list config.yaml and issue files
            folder_name = self._get_folder_from_path(path)
            if folder_name and folder_name in self.folders:
                yield 'config.yaml'
                
                folder = self.folders[folder_name]
                
                for issue in folder.issues:
                    yield f"{issue.key}.txt"
    
    def mkdir(self, path, mode):
        """Create a new query folder."""
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        # Only allow creating folders at root level
        if folder_name and not filename:
            if folder_name in self.folders:
                raise FuseOSError(errno.EEXIST)
            
            # Create new query folder with default config
            self.folders[folder_name] = QueryFolder(folder_name)
            print(f"Created query folder: {folder_name}")
        else:
            raise FuseOSError(errno.EACCES)
    
    def rmdir(self, path):
        """Remove a query folder."""
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        # Only allow removing folders at root level
        if folder_name and not filename:
            if folder_name in self.folders:
                del self.folders[folder_name]
                print(f"Removed query folder: {folder_name}")
            else:
                raise FuseOSError(errno.ENOENT)
        else:
            raise FuseOSError(errno.EACCES)
    
    def open(self, path, flags):
        """Open a file."""
        # Allow opening version.txt at root
        if path == '/version.txt':
            return 0
        
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        if not folder_name or not filename:
            raise FuseOSError(errno.ENOENT)
        
        if folder_name not in self.folders:
            raise FuseOSError(errno.ENOENT)
        
        # Allow opening config.yaml and issue files
        if filename == 'config.yaml' or filename.endswith('.txt'):
            return 0
        
        raise FuseOSError(errno.ENOENT)
    
    def read(self, path, size, offset, fh):
        """Read file contents."""
        # Handle version.txt at root
        if path == '/version.txt':
            content = self._get_root_version_content().encode('utf-8')
            return content[offset:offset + size]
        
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        if not folder_name or not filename or folder_name not in self.folders:
            raise FuseOSError(errno.ENOENT)
        
        folder = self.folders[folder_name]
        
        # Read config.yaml
        if filename == 'config.yaml':
            content = folder.to_yaml().encode('utf-8')
            return content[offset:offset + size]
        
        # Read issue file
        if filename.endswith('.txt'):
            content = self._get_issue_file_content(folder_name, filename)
            if content is not None:
                return content[offset:offset + size]
        
        raise FuseOSError(errno.ENOENT)
    
    def write(self, path, data, offset, fh):
        """Write to config.yaml file."""
        folder_name = self._get_folder_from_path(path)
        filename = self._get_filename_from_path(path)
        
        # Only allow writing to config.yaml
        if not self._is_config_file(path):
            raise FuseOSError(errno.EACCES)
        
        if folder_name not in self.folders:
            raise FuseOSError(errno.ENOENT)
        
        # Store the write in a temporary buffer
        if path not in self.file_handles:
            self.file_handles[path] = bytearray()
        
        # Expand buffer if needed
        if offset + len(data) > len(self.file_handles[path]):
            self.file_handles[path].extend(b'\0' * (offset + len(data) - len(self.file_handles[path])))
        
        # Write data at offset
        self.file_handles[path][offset:offset + len(data)] = data
        
        return len(data)
    
    def truncate(self, path, length, fh=None):
        """Truncate file to specified length."""
        if not self._is_config_file(path):
            raise FuseOSError(errno.EACCES)
        
        folder_name = self._get_folder_from_path(path)
        if folder_name not in self.folders:
            raise FuseOSError(errno.ENOENT)
        
        # Initialize or truncate buffer
        if path not in self.file_handles:
            self.file_handles[path] = bytearray(length)
        else:
            if length < len(self.file_handles[path]):
                self.file_handles[path] = self.file_handles[path][:length]
            else:
                self.file_handles[path].extend(b'\0' * (length - len(self.file_handles[path])))
    
    def flush(self, path, fh):
        """Flush file changes."""
        if not self._is_config_file(path):
            return
        
        folder_name = self._get_folder_from_path(path)
        if folder_name not in self.folders:
            return
        
        # Process config.yaml changes
        if path in self.file_handles:
            yaml_content = bytes(self.file_handles[path]).decode('utf-8')
            folder = self.folders[folder_name]
            
            # Parse YAML and update configuration
            old_enabled = folder.enabled
            old_jql = folder.jira_config.get('jql', '')
            folder.from_yaml(yaml_content)
            new_jql = folder.jira_config.get('jql', '')
            
            # If enabled or JQL changed, update issues
            if folder.enabled and new_jql and (old_enabled != folder.enabled or old_jql != new_jql):
                print(f"Configuration changed for {folder_name}, fetching issues...")
                folder.update_issues(self.jira)
            elif not folder.enabled or not new_jql:
                # Clear issues if disabled or jql is empty
                folder.issues = []
    
    def release(self, path, fh):
        """Release (close) file."""
        if path in self.file_handles:
            del self.file_handles[path]
        return 0
    
    def unlink(self, path):
        """Delete a file - not allowed for issue files, only config cleanup."""
        raise FuseOSError(errno.EACCES)


def main(mountpoint):
    """
    Main function to run the JIRA FUSE filesystem.
    """
    # Ensure the mountpoint directory exists
    if not os.path.isdir(mountpoint):
        print(f"Mountpoint directory '{mountpoint}' does not exist. Creating it.")
        os.makedirs(mountpoint)
    
    # Use the global JIRA client
    print(f"Connecting to JIRA at: {jira_url}")
    
    # Create and mount filesystem
    print(f"Mounting JiraFS filesystem to: {mountpoint}")
    print("Usage:")
    print("  1. Create a folder: mkdir <mountpoint>/my_query")
    print("  2. Edit config: vi <mountpoint>/my_query/config.yaml")
    print("  3. Configure with:")
    print("     enabled: true")
    print("     jira:")
    print("       - jql: 'your JQL query'")
    print("  4. Issues will appear as .txt files in the folder")
    print("\nPress Ctrl+C to unmount\n")
    
    FUSE(JiraFS(jira_client), mountpoint, foreground=True, allow_other=False)
    print(f"Filesystem unmounted from: {mountpoint}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python issuefs.py <mountpoint>")
        print("Example: python issuefs.py /tmp/jira")
        sys.exit(1)
    
    mount_point = sys.argv[1]
    main(mount_point)

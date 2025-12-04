#!/usr/bin/env python3

import os
import sys
import stat
import errno
import time
import yaml
import atexit
from pathlib import Path
from fuse import FUSE, FuseOSError, Operations
from dotenv import load_dotenv

from issue_api.jira_api import Jira
from issue_api.github_api import GitHub
from issue_api.bugzilla_api import Bugzilla

# --- SECRETS ---
load_dotenv()

# Initialize all available clients
clients = {}

# JIRA client
jira_api_token = os.getenv('JIRA_API_TOKEN')
jira_url = os.getenv('JIRA_URL')
if jira_api_token and jira_url:
    clients['jira'] = Jira(jira_url, jira_api_token)
    print(f"✓ JIRA client initialized")
else:
    print("⚠ JIRA client not configured (JIRA_API_TOKEN and JIRA_URL required)")

# GitHub client
github_api_token = os.getenv('GITHUB_API_TOKEN')
github_url = os.getenv('GITHUB_URL')
if github_api_token and github_url:
    clients['github'] = GitHub(github_url, github_api_token)
    print(f"✓ GitHub client initialized")
else:
    print("⚠ GitHub client not configured (GITHUB_API_TOKEN and GITHUB_URL required)")

# Bugzilla client
bugzilla_api_token = os.getenv('BUGZILLA_API_TOKEN')
bugzilla_url = os.getenv('BUGZILLA_URL')
if bugzilla_api_token and bugzilla_url:
    clients['bugzilla'] = Bugzilla(bugzilla_url, bugzilla_api_token)
    print(f"✓ Bugzilla client initialized")
else:
    print("⚠ Bugzilla client not configured (BUGZILLA_API_TOKEN and BUGZILLA_URL required)")

# Legacy support - keep old variable names for backward compatibility
jira_client = clients.get('jira')
github_client = clients.get('github')


class QueryFolder:
    """Represents a query folder with its configuration and cached issues."""
    
    def __init__(self, name):
        self.name = name
        self.enabled = False
        self.persistent = False  # Flag to persist this query on unmount
        self.jira_config = {'jql': '', 'issues': []}
        self.github_config = {'repo': '', 'q': '', 'issues': []}
        self.bugzilla_config = {'query': '', 'issues': []}
        self.issues = []
        self.last_updated = 0
        
    def to_yaml(self):
        """Convert configuration to YAML string."""
        # Dict maintains insertion order in Python 3.7+
        config = {
            'enabled': self.enabled,
            'persistent': self.persistent,
            'jira': [self.jira_config],
            'github': [self.github_config],
            'bugzilla': [self.bugzilla_config]
        }
        return yaml.dump(config, default_flow_style=False, sort_keys=False)
    
    def from_yaml(self, yaml_content):
        """Load configuration from YAML string."""
        try:
            data = yaml.safe_load(yaml_content)
            if data:
                self.enabled = data.get('enabled', False)
                self.persistent = data.get('persistent', False)
                
                # Load JIRA config
                jira_list = data.get('jira', [])
                if jira_list and isinstance(jira_list, list) and len(jira_list) > 0:
                    self.jira_config = jira_list[0]
                    # Ensure 'issues' key exists and is a list
                    if 'issues' not in self.jira_config:
                        self.jira_config['issues'] = []
                    elif not isinstance(self.jira_config['issues'], list):
                        self.jira_config['issues'] = []
                else:
                    self.jira_config = {'jql': '', 'issues': []}
                
                # Load GitHub config
                github_list = data.get('github', [])
                if github_list and isinstance(github_list, list) and len(github_list) > 0:
                    self.github_config = github_list[0]
                    # Ensure 'issues' key exists and is a list
                    if 'issues' not in self.github_config:
                        self.github_config['issues'] = []
                    elif not isinstance(self.github_config['issues'], list):
                        self.github_config['issues'] = []
                else:
                    self.github_config = {'repo': '', 'q': '', 'issues': []}
                
                # Load Bugzilla config
                bugzilla_list = data.get('bugzilla', [])
                if bugzilla_list and isinstance(bugzilla_list, list) and len(bugzilla_list) > 0:
                    self.bugzilla_config = bugzilla_list[0]
                    # Ensure 'issues' key exists and is a list
                    if 'issues' not in self.bugzilla_config:
                        self.bugzilla_config['issues'] = []
                    elif not isinstance(self.bugzilla_config['issues'], list):
                        self.bugzilla_config['issues'] = []
                else:
                    self.bugzilla_config = {'query': '', 'issues': []}
        except yaml.YAMLError as e:
            print(f"Error parsing YAML: {e}")
    
    def update_issues(self, clients_dict):
        """Fetch issues from all configured trackers if enabled."""
        # Clean up
        self.issues = []
        self.last_updated = time.time()
        
        # Track unique issue keys to avoid duplicates
        seen_keys = set()
        
        if not self.enabled:
            return
        
        # Define tracker configurations
        tracker_configs = [
            {
                'name': 'jira',
                'client': clients_dict.get('jira'),
                'config': self.jira_config,
                'query_key': 'jql',
                'issues_key': 'issues',
                'search_method': lambda client, query: client.search(query),
                'get_issue_method': lambda client, issue_id: client.get_issue(issue_id),
            },
            {
                'name': 'github',
                'client': clients_dict.get('github'),
                'config': self.github_config,
                'query_key': 'q',
                'issues_key': 'issues',
                'repo_key': 'repo',
                'search_method': lambda client, query, repo: client.search(query, repo),
                'get_issue_method': lambda client, issue_id, repo: client.get_issue(issue_id, repo),
            },
            {
                'name': 'bugzilla',
                'client': clients_dict.get('bugzilla'),
                'config': self.bugzilla_config,
                'query_key': 'query',
                'issues_key': 'issues',
                'search_method': lambda client, query: client.search(query),
                'get_issue_method': lambda client, issue_id: client.get_issue(issue_id),
            }
        ]
        
        # Process each tracker
        for tracker in tracker_configs:
            client = tracker['client']
            if not client:
                continue
            
            config = tracker['config']
            tracker_name = tracker['name'].upper()
            
            # Fetch issues from query
            query = config.get(tracker['query_key'], '')
            
            # For GitHub, also check if repo is configured
            if tracker_name == 'GITHUB':
                repo = config.get(tracker.get('repo_key', ''), '')
                if query and repo:
                    try:
                        query_issues = tracker['search_method'](client, query, repo)
                        for issue in query_issues:
                            if issue.key not in seen_keys:
                                self.issues.append(issue)
                                seen_keys.add(issue.key)
                        print(f"Updated {self.name} ({tracker_name} query): found {len(query_issues)} issues")
                    except Exception as e:
                        print(f"Error fetching {tracker_name} issues for {self.name}: {e}")
            else:
                # For JIRA and Bugzilla
                if query:
                    try:
                        query_issues = tracker['search_method'](client, query)
                        for issue in query_issues:
                            if issue.key not in seen_keys:
                                self.issues.append(issue)
                                seen_keys.add(issue.key)
                        print(f"Updated {self.name} ({tracker_name} query): found {len(query_issues)} issues")
                    except Exception as e:
                        print(f"Error fetching {tracker_name} issues for {self.name}: {e}")
            
            # Fetch explicitly specified issues
            issues_list = config.get(tracker['issues_key'], [])
            if issues_list:
                print(f"Fetching {len(issues_list)} explicitly specified {tracker_name} issue(s)...")
                for issue_id in issues_list:
                    if issue_id not in seen_keys:
                        try:
                            # Special handling for GitHub which needs repo
                            if tracker_name == 'GITHUB':
                                repo = config.get(tracker.get('repo_key', ''), '')
                                if repo:
                                    issue = tracker['get_issue_method'](client, issue_id, repo)
                                else:
                                    print(f"  ✗ Warning: Cannot fetch {tracker_name} issue {issue_id} - no repo configured")
                                    continue
                            else:
                                issue = tracker['get_issue_method'](client, issue_id)
                            
                            if issue:
                                self.issues.append(issue)
                                seen_keys.add(issue.key)
                                print(f"  ✓ Fetched {tracker_name} issue: {issue_id}")
                            else:
                                print(f"  ✗ Warning: {tracker_name} issue {issue_id} not found or could not be fetched")
                        except Exception as e:
                            print(f"  ✗ Warning: Error fetching {tracker_name} issue {issue_id}: {e}")
                    else:
                        print(f"  - Skipped {tracker_name} issue {issue_id} (already in results)")
        
        # Check if we have any valid configuration
        has_valid_config = False
        for tracker in tracker_configs:
            config = tracker['config']
            query = config.get(tracker['query_key'], '')
            issues_list = config.get(tracker['issues_key'], [])
            
            if tracker['name'] == 'github':
                repo = config.get(tracker.get('repo_key', ''), '')
                if (query and repo) or (repo and issues_list):
                    has_valid_config = True
                    break
            else:
                if query or issues_list:
                    has_valid_config = True
                    break
        
        if not has_valid_config:
            print(f"Warning: {self.name} is enabled but has no valid configuration")
            self.issues = []
        
        print(f"Final issue count for {self.name}: {len(self.issues)}")
        return

class IssueFS(Operations):
    """
    FUSE filesystem that mounts issues from JIRA, GitHub, and Bugzilla as files.
    
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
    
    def __init__(self, clients_dict, mountpoint, config_file=None):
        self.clients = clients_dict
        # Legacy attributes for backward compatibility
        self.jira = clients_dict.get('jira')
        self.github = clients_dict.get('github')
        self.bugzilla = clients_dict.get('bugzilla')
        
        self.folders = {}  # folder_name -> QueryFolder
        self.file_handles = {}  # path -> content
        self.now = time.time()
        self.mountpoint = os.path.abspath(mountpoint)
        
        # Setup config file path
        # Priority: 1. Parameter, 2. Environment variable, 3. Default
        if config_file is None:
            env_config = os.getenv('PERSISTENT_CONFIG')
            if env_config:
                config_file = Path(env_config)
                print(f"Using persistent config from env: {config_file}")
            else:
                config_file = Path.home() / '.issuefs' / 'persistent.yaml'
        else:
            config_file = Path(config_file)
        
        self.config_file = config_file
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize config file if it doesn't exist
        if not self.config_file.exists():
            self._initialize_config_file()
        
        # Load persistent configurations for this mountpoint
        self._load_config()
        
        # Test connections for all available clients
        self.version_info = {}
        for client_name, client in self.clients.items():
            if client:
                print(f"Testing {client_name.upper()} connection...")
                version_info = client.version()
                self.version_info[client_name] = version_info
                
                if version_info.get('success'):
                    print(f"✓ Connected to {version_info.get('server_title', client_name.upper())}")
                    print(f"✓ Version: {version_info.get('version', 'unknown')}")
                    if 'base_url' in version_info:
                        print(f"✓ Base URL: {version_info['base_url']}")
                    if 'url' in version_info:
                        print(f"✓ Base URL: {version_info['url']}")
                    if 'authenticated_user' in version_info:
                        print(f"✓ Authenticated as: {version_info['authenticated_user']}")
                else:
                    print(f"✗ Warning: Could not connect to {client_name.upper()}: {version_info.get('error', 'Unknown error')}")
                    print(f"  Filesystem will still mount, but {client_name.upper()} queries may fail.")
                print()
       
        # Register cleanup handler for saving config on exit
        atexit.register(self._save_config)
        
    def _get_config_header(self):
        """Generate the header comment for the persistent config file."""
        lines = [
            "# issuefs - persistent configuration",
            "# This file stores persistent query folder configurations",
            "# across multiple mountpoints.",
            "#",
            "# Format:",
            "#   mountpoints:",
            "#     /path/to/mountpoint:",
            "#       folders:",
            "#         query_name:",
            "#           enabled: true",
            "#           persistent: true",
            "#           jira_config:",
            "#             jql: 'your JQL query'",
            "#             issues: []",
            "#           github_config:",
            "#             repo: 'owner/repo'",
            "#             q: 'your GitHub search query'",
            "#             issues: []",
            "#           bugzilla_config:",
            "#             query: 'your Bugzilla search query'",
            "#             issues: []",
            "#",
            "# This file is automatically managed by issuefs.",
            "# Manual editing is supported but be careful with YAML syntax.",
            "",
        ]
        return "\n".join(lines) + "\n"
        
    def _initialize_config_file(self):
        """Initialize a new persistent config file with header comment."""
        try:
            with open(self.config_file, 'w') as f:
                f.write(self._get_config_header())
                yaml.dump({'mountpoints': {}}, f, default_flow_style=False, sort_keys=False)
            print(f"Created new persistent config file: {self.config_file}")
        except Exception as e:
            print(f"Warning: Could not create config file: {e}")
        
    def _load_config(self):
        """Load persistent configurations for this mountpoint from YAML file."""
        if not self.config_file.exists():
            print("No persistent configuration found.")
            return
        
        try:
            with open(self.config_file, 'r') as f:
                data = yaml.safe_load(f)
            
            if not data or 'mountpoints' not in data:
                print("No persistent configuration found.")
                return
            
            # Get configurations for this specific mountpoint
            mountpoint_config = data['mountpoints'].get(self.mountpoint, {})
            folders_config = mountpoint_config.get('folders', {})
            
            if not folders_config:
                print("No persistent queries for this mountpoint.")
                return
            
            print(f"Loading {len(folders_config)} persistent query folder(s)...")
            
            for folder_name, config in folders_config.items():
                folder = QueryFolder(folder_name)
                folder.enabled = config.get('enabled', False)
                folder.persistent = config.get('persistent', False)
                folder.jira_config = config.get('jira_config', {'jql': '', 'issues': []})
                folder.github_config = config.get('github_config', {'repo': '', 'q': '', 'issues': []})
                folder.bugzilla_config = config.get('bugzilla_config', {'query': '', 'issues': []})
                
                # Ensure 'issues' key exists in configs
                if 'issues' not in folder.jira_config:
                    folder.jira_config['issues'] = []
                if 'issues' not in folder.github_config:
                    folder.github_config['issues'] = []
                if 'issues' not in folder.bugzilla_config:
                    folder.bugzilla_config['issues'] = []
                
                self.folders[folder_name] = folder
                
                # Display preview of config
                jql_preview = folder.jira_config.get('jql', '')[:50]
                if len(folder.jira_config.get('jql', '')) > 50:
                    jql_preview += '...'
                
                github_repo = folder.github_config.get('repo', '')
                github_q = folder.github_config.get('q', '')[:30]
                if len(folder.github_config.get('q', '')) > 30:
                    github_q += '...'
                
                bugzilla_query = folder.bugzilla_config.get('query', '')[:30]
                if len(folder.bugzilla_config.get('query', '')) > 30:
                    bugzilla_query += '...'
                
                if jql_preview:
                    print(f"  ✓ Loaded: {folder_name} (enabled={folder.enabled}, jql='{jql_preview}')")
                elif github_repo:
                    print(f"  ✓ Loaded: {folder_name} (enabled={folder.enabled}, github={github_repo}, q='{github_q}')")
                elif bugzilla_query:
                    print(f"  ✓ Loaded: {folder_name} (enabled={folder.enabled}, bugzilla query='{bugzilla_query}')")
                else:
                    print(f"  ✓ Loaded: {folder_name} (enabled={folder.enabled}, no query)")
                
                # Fetch issues if enabled
                if folder.enabled:
                    folder.update_issues(self.clients)
                    
        except yaml.YAMLError as e:
            print(f"Error parsing config file: {e}")
        except Exception as e:
            print(f"Error loading config: {e}")
    
    def _save_config(self):
        """Save persistent configurations for this mountpoint to YAML file."""
        # Collect only persistent folders
        persistent_folders = {
            name: {
                'enabled': folder.enabled,
                'persistent': folder.persistent,
                'jira_config': folder.jira_config,
                'github_config': folder.github_config,
                'bugzilla_config': folder.bugzilla_config
            }
            for name, folder in self.folders.items()
            if folder.persistent
        }
        
        if not persistent_folders:
            print("\nNo persistent queries to save.")
            return
        
        # Ensure directory exists
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing config or create new one
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    data = yaml.safe_load(f) or {}
            except (yaml.YAMLError, Exception) as e:
                print(f"Warning: Could not parse existing config, creating new one: {e}")
                data = {}
        else:
            data = {}
        
        # Ensure mountpoints key exists
        if 'mountpoints' not in data:
            data['mountpoints'] = {}
        
        # Update this mountpoint's configuration
        data['mountpoints'][self.mountpoint] = {
            'folders': persistent_folders,
            'last_updated': time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        # Save to file
        try:
            with open(self.config_file, 'w') as f:
                # Write header comment
                f.write(self._get_config_header())
                # Write YAML data
                yaml.dump(data, f, default_flow_style=False, sort_keys=False)
            print(f"\n✓ Saved {len(persistent_folders)} persistent query folder(s) to {self.config_file}")
            for name in persistent_folders.keys():
                print(f"  - {name}")
        except Exception as e:
            print(f"\n✗ Error saving config: {e}")
        
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
        
        lines = []
        
        # Map of client names to display names
        client_display_names = {
            'jira': 'JIRA',
            'github': 'GitHub',
            'bugzilla': 'Bugzilla'
        }
        
        for client_name in ['jira', 'github', 'bugzilla']:
            if client_name not in self.version_info:
                continue
            
            version_info = self.version_info[client_name]
            display_name = client_display_names.get(client_name, client_name.upper())
            
            lines.append(f"{display_name} Server Information")
            lines.append(f"=" * 40)
            
            if version_info.get('success'):
                lines.append(f"Server: {version_info.get('server_title', display_name)}")
                lines.append(f"Version: {version_info.get('version', 'unknown')}")
                
                if 'base_url' in version_info:
                    lines.append(f"Base URL: {version_info['base_url']}")
                if 'url' in version_info:
                    lines.append(f"Base URL: {version_info['url']}")
                if 'authenticated_user' in version_info:
                    lines.append(f"Authenticated as: {version_info['authenticated_user']}")
                
                lines.append("")
            else:
                lines.append(f"Error: {version_info.get('error', 'Unknown error')}")
                lines.append("")
        
        lines.append(f"Connections tested at mount time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.now))}")
        return "\n".join(lines)


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
            
            # Store old configuration
            old_enabled = folder.enabled
            old_jql = folder.jira_config.get('jql', '')
            old_jira_issues = folder.jira_config.get('issues', [])
            old_github_repo = folder.github_config.get('repo', '')
            old_github_q = folder.github_config.get('q', '')
            old_github_issues = folder.github_config.get('issues', [])
            old_bugzilla_query = folder.bugzilla_config.get('query', '')
            old_bugzilla_issues = folder.bugzilla_config.get('issues', [])
            
            folder.from_yaml(yaml_content)
            
            # Get new configuration
            new_jql = folder.jira_config.get('jql', '')
            new_jira_issues = folder.jira_config.get('issues', [])
            new_github_repo = folder.github_config.get('repo', '')
            new_github_q = folder.github_config.get('q', '')
            new_github_issues = folder.github_config.get('issues', [])
            new_bugzilla_query = folder.bugzilla_config.get('query', '')
            new_bugzilla_issues = folder.bugzilla_config.get('issues', [])
            
            # Check if any config changed
            config_changed = (
                old_enabled != folder.enabled or 
                old_jql != new_jql or 
                old_jira_issues != new_jira_issues or
                old_github_repo != new_github_repo or 
                old_github_q != new_github_q or
                old_github_issues != new_github_issues or
                old_bugzilla_query != new_bugzilla_query or
                old_bugzilla_issues != new_bugzilla_issues
            )
            
            # If enabled and something changed, update issues
            if folder.enabled and config_changed:
                # Check if there's any valid config (query or explicit issues)
                has_jira_config = new_jql or new_jira_issues
                has_github_config = (new_github_repo and (new_github_q or new_github_issues))
                has_bugzilla_config = new_bugzilla_query or new_bugzilla_issues
                
                if has_jira_config or has_github_config or has_bugzilla_config:
                    print(f"Configuration changed for {folder_name}, fetching issues...")
                    folder.update_issues(self.clients)
            elif not folder.enabled or not (new_jql or new_jira_issues or 
                                           (new_github_repo and (new_github_q or new_github_issues)) or
                                           new_bugzilla_query or new_bugzilla_issues):
                # Clear issues if disabled or no valid config
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
    Main function to run the IssueFS FUSE filesystem.
    """
    # Ensure the mountpoint directory exists
    if not os.path.isdir(mountpoint):
        print(f"Mountpoint directory '{mountpoint}' does not exist. Creating it.")
        os.makedirs(mountpoint)
    
    # Create and mount filesystem
    print(f"Mounting IssueFS filesystem to: {mountpoint}")
    print("Usage:")
    print("  1. Create a folder: mkdir <mountpoint>/my_query")
    print("  2. Edit config: vi <mountpoint>/my_query/config.yaml")
    print("  3. Configure with:")
    print("     enabled: true")
    print("     persistent: true  # Set to true to save on unmount")
    print("     jira:")
    print("       - jql: 'your JQL query'")
    print("     github:")
    print("       - repo: 'owner/repo'")
    print("         q: 'your GitHub search query'")
    print("     bugzilla:")
    print("       - query: 'your Bugzilla search query'")
    print("  4. Issues will appear as .txt files in the folder")
    print("\nPress Ctrl+C to unmount\n")
    
    FUSE(IssueFS(clients, mountpoint), mountpoint, foreground=True, allow_other=False)
    print(f"Filesystem unmounted from: {mountpoint}")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python issuefs.py <mountpoint>")
        print("Example: python issuefs.py /tmp/jira")
        sys.exit(1)
    
    mount_point = sys.argv[1]
    main(mount_point)

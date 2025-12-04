import requests

from .issue import IssueInfo, IssueComment
from .client import IssueTrackerClient


class IssueInfo_GitHub(IssueInfo):
    """GitHub-specific issue information."""
    
    def __init__(self, number, summary, description, github_url=None, repo=None):
        super().__init__(f'GITHUB-{number}', summary, description)
        self.github_url = github_url
        self.repo = repo  # Format: "owner/repo"
        self.number = number
    
    @property
    def id(self):
        """Return numeric issue number for GitHub compatibility."""
        return self.number
    
    def __str__(self):
        if self.repo:
            return f'GitHub issue {self.repo}#{self.id}: {self.summary}'
        return f'GitHub issue #{self.id}: {self.summary}'
    
    def to_html(self):
        if self.github_url and self.repo:
            return f'<a href="{self.github_url}/{self.repo}/issues/{self.id}">#{self.id}</a>: {self.summary}'
        return f'#{self.id}: {self.summary}'

    def to_ai(self):
        return super().to_ai(tracker_type="GitHub")


class GitHub(IssueTrackerClient):
    def __init__(self, url, token):
        """
        Initialize GitHub API client.
        
        Args:
            token: GitHub personal access token
        """
        super().__init__(url, token)

    def headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'
        }

    def search(self, query, repo, fields=None):
        """
        Search for GitHub issues.
        
        Args:
            query: Search query string (GitHub search syntax)
            repo: Repository in format "owner/repo" (required)
            fields: List of fields to include (currently supports 'comments')
        
        Returns:
            List of IssueInfo_GitHub objects
        """
        if fields is None:
            fields = ['comments']
        
        # Determine if comments should be included
        include_comments = 'comments' in fields
        
        # Build search query - add repo filter if not already in query
        if f"repo:{repo}" not in query:
            full_query = f"{query} repo:{repo}"
        else:
            full_query = query
        
        # GitHub Search API
        url_to_get = f'{self.url}/search/issues'
        params = {
            'q': full_query,
            'per_page': 100,
            'sort': 'updated',
            'order': 'desc'
        }
        
        result = requests.get(url_to_get, headers=self.headers(), params=params).json()
        
        issues = []
        for item in result.get('items', []):
            i = IssueInfo_GitHub(
                item['number'],
                item['title'],
                item.get('body') or '',
                github_url="https://github.com",
                repo=repo
            )
            if include_comments:
                i.comments = self.get_comments(item['number'], repo=repo)
            issues.append(i)
        
        return issues

    def get_comments(self, issue_number, repo):
        """
        Retrieve comments for a specific GitHub issue.
        
        Args:
            issue_number: Issue number
            repo: Repository in format "owner/repo" (required)
        
        Returns:
            List of IssueComment objects
        """
        api_endpoint = f"{self.url}/repos/{repo}/issues/{issue_number}/comments"
        result = requests.get(api_endpoint, headers=self.headers()).json()
        
        comments = []
        for comment in result:
            comments.append(IssueComment(
                comment['user']['login'],
                comment['body'],
                comment['created_at']
            ))
        return comments

    def get_issue(self, issue_number, repo, include_comments=True):
        """
        Get a single issue by its number.
        
        Args:
            issue_number: Issue number (integer or string)
            repo: Repository in format "owner/repo" (required)
            include_comments: Whether to include comments (default: True)
        
        Returns:
            IssueInfo_GitHub object or None if issue not found
        """
        try:
            url_to_get = f'{self.url}/repos/{repo}/issues/{issue_number}'
            result = requests.get(url_to_get, headers=self.headers(), timeout=10)
            result.raise_for_status()
            data = result.json()
            
            i = IssueInfo_GitHub(
                data['number'],
                data['title'],
                data.get('body') or '',
                github_url="https://github.com",
                repo=repo
            )
            if include_comments:
                i.comments = self.get_comments(data['number'], repo=repo)
            return i
        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch GitHub issue #{issue_number} from {repo}: {e}")
            return None

    def api(self, issue_number, repo, fields=None):
        """
        Get specific fields from a GitHub issue.
        
        Args:
            issue_number: Issue number
            repo: Repository in format "owner/repo" (required)
            fields: List of fields to retrieve (maps to GitHub API fields)
        
        Returns:
            Dictionary with requested fields
        """
        if fields is None:
            fields = ['title']
        
        url_to_get = f'{self.url}/repos/{repo}/issues/{issue_number}'
        result = requests.get(url_to_get, headers=self.headers()).json()
        
        # Map common field names
        field_mapping = {
            'summary': 'title',
            'description': 'body',
            'status': 'state',
            'assignee': 'assignee',
            'labels': 'labels',
            'created': 'created_at',
            'updated': 'updated_at'
        }
        
        out = {}
        for f in fields:
            # Try to map the field name
            api_field = field_mapping.get(f, f)
            out[f] = result.get(api_field, None)
        
        return out

    def version(self):
        """
        Test connection to GitHub API and return server information.
        Returns a dict with version info if successful, error info if connection fails.
        """
        try:
            # Check authentication by getting user info
            user_url = f'{self.url}/user'
            user_result = requests.get(user_url, headers=self.headers(), timeout=10)
            user_result.raise_for_status()
            user_data = user_result.json()
            
            # Extract API version from response headers
            # GitHub API version is in X-GitHub-Api-Version-Selected or X-GitHub-Media-Type headers
            api_version = user_result.headers.get(
                'X-GitHub-Api-Version-Selected',
                user_result.headers.get('X-GitHub-Api-Version', '2022-11-28')
            )

            return {
                'success': True,
                'version': f'{api_version}',
                'server_title': 'GitHub',
                'url': self.url,
                'authenticated_user': user_data.get('login', 'unknown'),
                'api_version': api_version
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }
import requests
import urllib.parse
import re

from .issue import IssueInfo, IssueComment
from .client import IssueTrackerClient


class IssueInfo_Bugzilla(IssueInfo):
    """Bugzilla-specific issue information."""
    
    def __init__(self, id, summary, description, bugzilla_url=None):
        # Bugzilla uses numeric IDs, convert to string for consistency
        super().__init__(f'BUGZILLA-{id}', summary, description)
        self.bugzilla_url = bugzilla_url
        # Store original numeric ID
        self._numeric_id = id
    
    @property
    def id(self):
        """Return numeric ID for Bugzilla compatibility."""
        return self._numeric_id
    
    def __str__(self):
        return f'Bugzilla issue {self.id}: {self.summary}'
    
    def to_html(self):
        if self.bugzilla_url:
            return f'<a href="{self.bugzilla_url}/show_bug.cgi?id={self.id}">bsc#{self.id}</a>: {self.summary}'
        return f'bsc#{self.id}: {self.summary}'

    def to_ai(self):
        return super().to_ai(tracker_type="Bugzilla")


class Bugzilla(IssueTrackerClient):
    def __init__(self, url, token):
        super().__init__(url, token)

    def headers(self):
        return {
            'Accept': 'application/json'
        }

    def params(self, id):
        return {
            'id': id, 
            'api_key': self.token
        }
    
    def params2(self):
        return {
            'api_key': self.token
        }

    def search(self, query, **kwargs):
        """
        Search for Bugzilla bugs.
        
        Args:
            query: Search query string (searches in summary field)
            **kwargs: Additional parameters (unused for now)
        
        Returns:
            List of IssueInfo_Bugzilla objects
        """
        # Example queries:
        #   summary=foo
        #   summary=foo&description=bar&product=zoo
        search_params = {
            "summary": rf"{query}",
            "order": ["last_change_time DESC"],
            "limit": 100
        }

        search_term_regex_filter = re.compile(rf"\b{query}\b")
        url_to_get = f'{self.url}/rest/bug?{urllib.parse.urlencode(search_params)}'
        result = requests.get(url_to_get, headers=self.headers(), params=self.params2()).json()
        issues = []
        for issue in result['bugs']:
            if search_term_regex_filter.search(issue['summary']):
                comments = self.get_comments(issue['id'])
                description_comment = comments[0] if comments else IssueComment('', '', '')
                comments = comments[1:] if len(comments) > 1 else []
                i = IssueInfo_Bugzilla(
                    issue['id'],
                    issue['summary'],
                    description_comment.text,
                    bugzilla_url=self.url
                    )
                i.comments = comments
                issues.append(i)
        return issues

    def get_comments(self, issue_id, **kwargs):
        """
        Get comments for a specific Bugzilla bug.
        
        Args:
            issue_id: Bugzilla bug ID
            **kwargs: Additional parameters (unused)
        
        Returns:
            List of IssueComment objects
        """
        url_to_get = f'{self.url}/rest/bug/{issue_id}/comment'
        result = requests.get(url_to_get, headers=self.headers(), params=self.params2()).json()
        comments = []
        for c in result['bugs'][str(issue_id)]['comments']:
            comments.append(IssueComment(
                c['creator'],
                c['text'],
                c['creation_time']
                ))
        return comments

    def get_issue(self, issue_id, include_comments=True, **kwargs):
        """
        Get a single issue by its ID.
        
        Args:
            issue_id: Bugzilla bug ID (numeric)
            include_comments: Whether to include comments (default: True)
        
        Returns:
            IssueInfo_Bugzilla object or None if issue not found
        """
        try:
            url_to_get = f'{self.url}/rest/bug/{issue_id}'
            result = requests.get(url_to_get, headers=self.headers(), params=self.params2(), timeout=10)
            result.raise_for_status()
            data = result.json()
            
            if 'bugs' not in data or len(data['bugs']) == 0:
                print(f"Warning: Bugzilla issue {issue_id} not found")
                return None
            
            bug = data['bugs'][0]
            
            # Get comments to extract description
            comments = self.get_comments(issue_id)
            description_comment = comments[0] if comments else IssueComment('', '', '')
            remaining_comments = comments[1:] if len(comments) > 1 else []
            
            i = IssueInfo_Bugzilla(
                bug['id'],
                bug['summary'],
                description_comment.text,
                bugzilla_url=self.url
            )
            if include_comments:
                i.comments = remaining_comments
            return i
        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch Bugzilla issue {issue_id}: {e}")
            return None

    def api(self, id, fields=['summary']):
        url_to_get = f'{self.url}/rest/bug'
        result = requests.get(url_to_get, headers=self.headers(), params=self.params(id)).json()
        out = {}
        for f in fields:
            if result['bugs'] == []:
                # Wrong ID probably
                out[f] = f'Error: Bug {id} could not be found!!!'
            else:
                out[f] = result['bugs'][0][f]
        return out

    def version(self):
        """
        Test connection to Bugzilla API and return server information.
        Returns a dict with version info if successful, None if connection fails.
        """
        try:
            url_to_get = f'{self.url}/rest/version'
            result = requests.get(url_to_get, headers=self.headers(), timeout=10)
            result.raise_for_status()
            data = result.json()
            return {
                'success': True,
                'version': data.get('version', 'unknown'),
                'base_url': self.url
            }
        except requests.exceptions.RequestException as e:
            return {
                'success': False,
                'error': str(e)
            }